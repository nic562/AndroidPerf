import os
import types

from adb import adb_commands
from adb import sign_pythonrsa
from adb.adb_protocol import InvalidResponseError, InvalidCommandError

from .base_adb import AdbInterface, AdbProxy
from .log import default as logging


class ReadConnectError(Exception):
    pass


class PyAdb(AdbInterface):
    """python-adb的封装"""

    @classmethod
    def get_proxy(cls, serial=None) -> AdbProxy:
        return AdbProxy(cls(serial))

    @staticmethod
    def my_load_rsa_key_path(file_path):
        # 原来的加载方法，在python3中问题兼容性问题
        with open(file_path + '.pub', 'rb') as f:
            pub = f.read()
        with open(file_path, 'rb') as f:
            pri = f.read()
        return sign_pythonrsa.PythonRSASigner(pub, pri)

    @classmethod
    def connect_dev(cls, adb_key_path, serial=None) -> adb_commands.AdbCommands:
        """
        连接设备，可指定连接的具体设备名
        :param adb_key_path: 与设备通讯的授权密钥
        :param serial: 可选，设备号 (可通过adb devices查看)，不提供则连接第一个
        :return:
        """
        dev = adb_commands.AdbCommands()
        try:
            dev.ConnectDevice(rsa_keys=[cls.my_load_rsa_key_path(os.path.expanduser(adb_key_path))], serial=serial)
        except InvalidCommandError as e:
            dev.Close()
            logging.warning(f'reconnect on error: {e}')
            return cls.connect_dev(adb_key_path, serial=serial)
        return dev

    def __init__(self, serial=None, adb_key_path='~/.android/adbkey', auto_connect=True):
        try:
            os.system('adb kill-server')
        except:
            pass
        self.serial = serial
        self.adb_key_path = adb_key_path
        self._adb = None
        if auto_connect:
            self.open_connect()

    @property
    def adb(self):
        if not self._adb:
            raise ValueError('Please connect device first!')
        return self._adb

    def get_device_serial(self) -> str:
        return self.serial

    def open_connect(self) -> adb_commands.AdbCommands:
        self._adb = self.connect_dev(self.adb_key_path, serial=self.serial)
        return self._adb

    def _on_read_error(self, e, cmd, clean_wrap, reconnect_on_err):
        if reconnect_on_err:
            logging.warning('trying to reconnect adb!')
            self.adb.Close()
            self.open_connect()
            return self.run_shell(cmd, clean_wrap, reconnect_on_err)
        else:
            raise ReadConnectError(e)

    def run_shell(self, cmd: str, clean_wrap=False, reconnect_on_err=True) -> str:
        """
        执行命令
        :param cmd: 命令内容
        :param clean_wrap: 是否清理结果换行
        :param reconnect_on_err: 命令执行过程中出现IO读写的错误时重新连接. 如果为False，则发生错误时将报错 ReadConnectError
        :return:
        """
        logging.debug(f'adb shell {cmd}')
        try:
            rs = self.adb.Shell(cmd)
            if clean_wrap:
                rs = rs.strip()
            return rs
        except InvalidResponseError as e:
            return self._on_read_error(e, cmd, clean_wrap, reconnect_on_err)
        except InvalidCommandError as e:
            return self._on_read_error(e, cmd, clean_wrap, reconnect_on_err)
        except AttributeError as e:
            return self._on_read_error(e, cmd, clean_wrap, reconnect_on_err)

    def stream_shell(self, cmd: str) -> types.GeneratorType:
        """
        执行命令，返回输出流的迭代器，每次返回一行输出结果
        :param cmd: 命令内容
        :return: 每行输出结果迭代
        """
        logging.debug(f'adb shell(Streaming) {cmd}')
        return self.adb.StreamingShell(cmd)

    def install_app(self, apk_path):
        return self.adb.Install(apk_path, grant_permissions=True, timeout_ms=1200000)

    def uninstall_app(self, app_bundle: str):
        return self.adb.Uninstall(app_bundle)

    def close(self):
        try:
            self.adb.Close()
        except:
            pass

    def push_file(self, local_path: str, device_path: str):
        return self.adb.Push(local_path, device_path)

    def pull_file(self, device_path: str, local_path: str):
        return self.adb.Pull(device_path, local_path)

    def devices(self):
        # 这里有坑，已经连接了设备的话，执行Devices 方法会报错，必须先断开连接
        logging.warning('listing devices need to disconnect current device!')
        self.close()
        return [(x.serial_number, '') for x in self._devices()]

    @staticmethod
    def _devices():
        # 请在连接设备前调用，否则会报错 # usb1.USBErrorAccess: LIBUSB_ERROR_ACCESS [-3]
        return adb_commands.AdbCommands.Devices()
