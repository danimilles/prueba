import os
import string
import sys
from random import choice, randint
from tkinter import Tk, Label, Button, TOP, Event, NORMAL, DISABLED, Text, END, Toplevel, Entry, BOTTOM

from django.conf.locale import tk

from finitefield.elliptic import EllipticCurve, Point
from finitefield.finitefield import FiniteField
from hashlib import blake2b

F = FiniteField(3851, 1)
E = EllipticCurve(a=F(324), b=F(1287))
G = Point(E, F(920), F(303))
VARIABLE_SIZE = 128
EXP_TIME = 30
devicestr = 'Device: '
serverstr = 'Server: '


def generate_x(num_bits):
    return os.urandom(num_bits // 8)


def generate_id(num_bits):
    return int.from_bytes(os.urandom(num_bits // 8), byteorder='big')


def hash_function(byte_string, size=64):
    h = blake2b(digest_size=size)
    h.update(byte_string)
    result = h.hexdigest()
    return int.from_bytes(bytes(result.encode()), byteorder='big')


def generate_r(length):
    letters = string.ascii_letters
    result_str = ''.join(choice(letters) for i in range(length))
    return bytes(result_str.encode())


def generate_ck(r, x, exp_time, id):
    integer = int.from_bytes(r, byteorder='big') | int.from_bytes(x, byteorder='big') | exp_time | id
    byte_string = integer.to_bytes(128, 'big')
    return hash_function(byte_string)


def generate_a(t, ck_prime):
    return hash_function((t | ck_prime.module()).to_bytes(128, 'big'))


def generate_n(num_bits):
    return randint(2, pow(2, num_bits))


def generate_hash_one_point(integer1, integer2, p1):
    m_p = integer2 * p1
    integer = integer1 | m_p.module()
    return hash_function(integer.to_bytes(128, 'big'))


def generate_hash_two_point(p1, integer1, p2):
    m_p = integer1 * p2
    integer = p1.module() | m_p.module()
    return hash_function(integer.to_bytes(128, 'big'))


class Register(object):
    def __init__(self, device, t, a_prime, exp_time):
        self.device = device
        self.t = t
        self.a_prime = a_prime
        self.exp_time = exp_time


class ServerSession(object):
    def __init__(self, n2, p1, p2, p3, p4):
        self.n2 = n2
        self.p1 = p1
        self.p2 = p2
        self.p3 = p3
        self.p4 = p4

    def create_session(p1, p2, a_prime):
        n2 = generate_n(VARIABLE_SIZE)
        p3 = n2 * G
        p4 = generate_hash_one_point(p2, n2, a_prime)
        return ServerSession(n2, p1, p2, p3, p4)

    def establish_connection(self, v):
        self.v = v
        self.sk = generate_hash_two_point(self.p3, self.n2, self.p1)
        return self


class DeviceSession(object):
    def __init__(self, n1, p1, p2):
        self.n1 = n1
        self.p1 = p1
        self.p2 = p2

    def create_session(ck_prime):
        n1 = generate_n(VARIABLE_SIZE)
        p1 = n1 * G
        p2 = generate_hash_two_point(p1, n1, ck_prime)
        return DeviceSession(n1, p1, p2)

    def establish_connection(self, t, p3, p4, a):
        self.t = t
        self.p3 = p3
        self.p4 = p4
        self.a = a
        self.v = generate_hash_one_point(p4, self.n1, p3)
        self.sk = generate_hash_two_point(p3, self.n1, p3)
        return self


class Server(object):
    def __init__(self):
        self.register_devices = {}
        self.active_devices_sessions = {}
        self.x = generate_x(VARIABLE_SIZE)

    def receive_id(self, device):
        r = generate_r(VARIABLE_SIZE)
        ck = generate_ck(r, self.x, EXP_TIME, device.id)
        ck_prime = ck * G
        t = int.from_bytes(r, byteorder='big') ^ hash_function(self.x)
        a = generate_a(t, ck_prime)
        a_prime = a * G
        self.register_devices[device.id] = Register(device, t, a_prime, EXP_TIME)
        print(serverstr + 'Sending Ck_prime (CK)...')
        device.receive_ck_prime(ck_prime)

    def receive_session_login(self, device_id, p1, p2):
        register = self.register_devices[device_id]
        r = register.t ^ hash_function(self.x)
        ck = generate_ck(r.to_bytes(128, 'big'), self.x, register.exp_time, device_id)
        p2_prime = generate_hash_two_point(p1, ck, p1)

        if p2_prime != p2:
            raise Exception(serverstr + 'P2 is not equal to P2_prime')

        session = ServerSession.create_session(p1, p2, register.a_prime)
        self.active_devices_sessions[device_id] = session
        print(serverstr + 'Sending session info (T,P3,P4)...')
        register.device.receive_session_info(register.t, session.p3, session.p4)

    def establish_connection(self, device_id, v):
        session = self.active_devices_sessions[device_id]
        v_prime = generate_hash_one_point(session.p4, session.n2, session.p1)

        if v_prime != v:
            raise Exception(serverstr + 'V is not equal to V_prime')

        self.active_devices_sessions[device_id].establish_connection(v)
        print(serverstr + 'Connection successful!')

    def receive(self, device_id, sk, msg):
        if self.active_devices_sessions[device_id].sk != sk:
            raise Exception(serverstr + 'SK not valid')

        print(serverstr + 'Message received: ' + msg)


class Device(object):
    def __init__(self):
        self.server = None
        self.active_server_session = None

    def register_in_server(self, server):
        self.server = server
        self.id = generate_id(VARIABLE_SIZE)
        print(devicestr + 'Registering (ID)...')
        server.receive_id(self)

    def receive_ck_prime(self, ck_prime):
        print(devicestr + 'Registered!')
        self.ck_prime = ck_prime

    def log_in_server(self):
        self.active_server_session = DeviceSession.create_session(self.ck_prime)
        print(devicestr + 'Initializing login (ID,P1,P2)...')
        self.server.receive_session_login(self.id, self.active_server_session.p1, self.active_server_session.p2)

    def receive_session_info(self, t, p3, p4):
        a = generate_a(t, self.ck_prime)
        p4_prime = generate_hash_one_point(self.active_server_session.p2, a, p3)

        if p4_prime != p4:
            raise Exception(devicestr + 'P4 is not equal to P4_prime')

        self.active_server_session.establish_connection(t, p3, p4, a)
        print(devicestr + 'Establishing connection (V)...')
        self.server.establish_connection(self.id, self.active_server_session.v)

    def send(self, msg):
        print(devicestr + 'Sending message...')
        self.server.receive(self.id, self.active_server_session.sk, msg)

    def logout(self):
        print(devicestr + 'Logged out!')
        self.server = None
        self.active_server_session = None


class PrintLogger():
    def __init__(self, textbox):
        self.textbox = textbox

    def write(self, text):
        self.textbox.insert(END, text)

    def flush(self):
        pass


class TestSystem(object):
    device = None
    server = Server()

    @staticmethod
    def register_device():
        TestSystem.device = Device()
        TestSystem.device.register_in_server(TestSystem.server)
        TestSystem.device.log_in_server()


        def send_message(event=None):
            TestSystem.device.send(entry.get())

        def logout():
            TestSystem.device.logout()
            window.destroy()

        window = Toplevel()
        window.geometry('200x100')
        entry = Entry(window)
        button2 = Button(window, text="Send", command=send_message)
        entry.bind('<Return>', send_message)
        entry.pack()
        button3 = Button(window, text="Logout device", command=logout)

        button3.pack(side=BOTTOM)
        button2.pack(side=BOTTOM)



if __name__ == "__main__":
    root = Tk()
    t = Text()
    t.pack()
    pl = PrintLogger(t)
    sys.stdout = pl

    button1 = Button(root, text="Register and log device", command=TestSystem.register_device)
    button1.pack(side=TOP)

    root.mainloop()
