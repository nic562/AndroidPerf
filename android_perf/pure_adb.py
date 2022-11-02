import os
import types

from ppadb.client import Client as AdbClient
from ppadb.device import Device
from ppadb import InstallError

from .base_adb import AdbInterface, AdbProxy
from .log import default as logging


class PureAdb(AdbInterface):
    """
    基于pure-python-adb的封装
    """

    def __init__(self, serial=None):
        self._dev = None
        self.serial = serial
        self.start_server()
        self.adb_client = AdbClient()
        self.connect(serial)

    @classmethod
    def get_proxy(cls, serial=None) -> AdbProxy:
        return AdbProxy(cls(serial))

    def get_device(self) -> Device:
        if self._dev:
            return self._dev
        raise RuntimeError("No device is connected! Please call `connect` first!")

    @staticmethod
    def start_server():
        os.system('adb start-server')

    def kill_server(self):
        return self.adb_client.kill()

    def version(self):
        return self.adb_client.version()

    def devices(self, state=None, return_obj=False):
        rs = self.adb_client.devices(state)
        if return_obj:
            return rs
        return [(x.serial, x.get_state()) for x in rs]

    def connect(self, serial=None):
        s = serial or self.serial
        if s:
            self._dev = self.adb_client.device(s)
            if not self._dev:
                raise RuntimeError(f'No device found for [{serial}]')
            self.serial = s
        else:
            devs = self.devices(self.adb_client.DEVICE, return_obj=True)
            if not devs:
                raise RuntimeError('No devices!')
            self._dev = devs[0]
            self.serial = self._dev.serial
        return self._dev

    def disconnect(self):
        if self._dev:
            self._dev = None

    def get_device_serial(self) -> str:
        return self.serial

    def shell(self, cmd, timeout_ms=None, clean_wrap=False, handler=None, ensure_unicode=True):
        """
        执行命令
        :param cmd: 命令内容
        :param timeout_ms: 命令执行超时时间
        :param clean_wrap: 是否清理结果换行
        :param handler: 结果处理函数
        :param ensure_unicode: decode/encode unicode True or False, default is True
            def func(connection):
                try:
                    while True:
                        d = connection.read(1024)
                        if not d:
                            break
                        print(d.decode('utf-8'))
                finally:
                    connection.close()
        :return:
        """
        logging.debug(f'adb shell {cmd}')
        rs = self.get_device().shell(cmd, handler=handler, timeout=timeout_ms,
                                     decode=ensure_unicode and 'utf8' or None)
        if clean_wrap and isinstance(rs, str):
            rs = rs.strip()
        return rs

    def stream_shell(self, cmd: str) -> types.GeneratorType:
        def handler(connection):
            try:
                while True:
                    d = connection.read(1024)
                    if not d:
                        break
                    yield d.decode('utf-8')
            finally:
                connection.close()

        return self.shell(cmd, handler=handler)

    def run_shell(self, cmd: str, clean_wrap=False) -> str:
        return self.shell(cmd, clean_wrap=clean_wrap)

    def close(self):
        return self.disconnect()

    def install_app(self, apk_path):
        if not os.path.isfile(apk_path):
            raise RuntimeError("file: %s does not exists" % (repr(apk_path)))
        try:
            self.get_device().install(apk_path, reinstall=True)
        except InstallError as e:
            raise InstallError(apk_path, e)

    def uninstall_app(self, app_bundle: str):
        return self.get_device().uninstall(app_bundle)

    def push_file(self, local_path: str, device_path: str):
        return self.get_device().push(local_path, device_path)

    def pull_file(self, device_path: str, local_path: str):
        return self.get_device().pull(device_path, local_path)
