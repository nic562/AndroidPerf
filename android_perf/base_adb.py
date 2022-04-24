import types
from abc import ABCMeta
import re

from .abstract_adb import AdbInterface
from .cpu import CPUUsageAdb
from .memory import MemoryAdb
from .traffic import TrafficAdb


class AndroidDevice(object):
    os_version = None
    sdk_version = None
    model = None
    brand = None
    account_password = None  # 设置权限、安装app时可能要较验设备账号密码

    def __str__(self):
        return f'品牌:{self.brand} 型号:{self.model} Android {self.os_version} (SDK {self.sdk_version})'


class AdbBase(AdbInterface, metaclass=ABCMeta):
    """扩展较多常用指令操作的adb抽象"""

    RE_APP_VERSION = re.compile(r'versionName=([\w\.]+)')

    def go_back(self):
        return self.run_shell('input keyevent BACK')

    def set_http_proxy(self, host_port: str):
        """
        设置 wifi 代理
        :param host_port: ip:端口 的格式
        :return:
        """
        rs = self.run_shell(f'settings put global http_proxy {host_port}')
        if rs.find('Permission denial') == -1:
            return rs
        raise RuntimeError('Wifi 代理因权限问题而设置失败，请尝试授权：'
                           '\n小米: 在开发者选项里，把“USB调试（安全设置）"打开即可; 或允许USB调试修改权限或模拟点击'
                           '\noppo：在开发者选项里，把"禁止权限监控"打开')

    def close_http_proxy(self):
        return self.set_http_proxy(':0')

    def get_device_resolution(self) -> (int, int):
        k = '_resolution'
        if not hasattr(self, k):
            rs = re.split(r'\s+', self.run_shell('wm size').strip())
            rs = rs[-1].split('x')
            setattr(self, k, (int(rs[0]), int(rs[1])))
        return getattr(self, k)

    def get_device_info(self, dev: AndroidDevice = None) -> AndroidDevice:
        d = dev or AndroidDevice()
        d.os_version = self.run_shell('getprop ro.build.version.release', True)
        d.sdk_version = self.run_shell('getprop ro.build.version.sdk', True)
        d.model = self.run_shell('getprop ro.product.model', True)
        d.brand = self.run_shell('getprop ro.product.brand', True)
        return d

    def launch_app(self, app_pkg: str, app_activity: str = None):
        m = app_activity and f'am start {app_pkg}/{app_activity}' or \
            f'monkey -p {app_pkg} -c android.intent.category.LAUNCHER 1'
        return self.run_shell(m)

    def get_app_version(self, app_bundle: str) -> str:
        rs = self.run_shell(f'pm dump {app_bundle} | grep "version"', True)
        v = self.RE_APP_VERSION.findall(rs)
        v = v and v[0] or None
        return v

    def clear_app(self, app_bundle: str):
        """
        清理缓存和数据
        :param app_bundle:
        :return:
        """
        return self.run_shell(f'pm clear {app_bundle}')

    def kill_app(self, app_bundle: str):
        return self.run_shell(f'am force-stop {app_bundle}', True)

    def find_processes(self, app_bundle: str) -> list:
        """
        每个app可能会有多个进程
        :param app_bundle:
        :return: list: [(进程ID，父进程ID，进程名)]
        """
        rs = self.run_shell(f'ps -A | grep {app_bundle}')
        ll = []
        for x in rs.split('\n'):
            d = re.split(r'\s+', x)
            if not d or not d[0]:
                continue
            ll.append((d[1], d[2], d[-1]))
        return ll

    def find_process_ids(self, app_bundle: str) -> list:
        return [p[0] for p in self.find_processes(app_bundle)]

    def find_main_process_id(self, app_bundle: str) -> str:
        for p in self.find_processes(app_bundle):
            if p[-1].find(':') == -1:
                return p[0]
        raise ValueError('No Process Found!')

    def get_app_user_id(self, app_bundle: str):
        """
        获取某个应用在系统中分配的用户ID，通常一个应用(不论有多少进程)有全局唯一的用户ID
        :param app_bundle:
        :return:
        """
        rs = self.run_shell(f'dumpsys package {app_bundle} | grep userId=')
        u = re.findall(r'userId=(\d+)', rs)
        if u:
            return u[0]
        raise ValueError(f'Matching userId error: {rs}')

    def cat_file(self, file_path):
        return self.run_shell(f'cat {file_path}')

    def del_file(self, file_path):
        return self.run_shell(f'rm {file_path}')

    def send_broadcast(self, broadcast_action: str, *args: str, **kv: str):
        vv = map(lambda x: f"-e {x[0]} {x[1]}", kv.items())
        return self.run_shell(
            f'am broadcast -a {broadcast_action} {" ".join(args)} {" ".join(vv)}')

    def ping(self, h: str) -> bool:
        rs = self.run_shell(f'ping -c 1 -W 1 {h}')
        return rs.rfind('1 received') != -1


class AdbProxy(AdbBase, CPUUsageAdb, MemoryAdb, TrafficAdb):
    """ADB 代理，用于衔接adb协议的不同底层实现"""

    def __init__(self, adb_implement: AdbInterface):
        self._impl = adb_implement

    def run_shell(self, cmd: str, clean_wrap=False) -> str:
        return self._impl.run_shell(cmd, clean_wrap=clean_wrap)

    def stream_shell(self, cmd: str) -> types.GeneratorType:
        return self._impl.stream_shell(cmd)

    def get_device_serial(self) -> str:
        return self._impl.get_device_serial()

    def close(self):
        return self._impl.close()

    def install_app(self, apk_path):
        return self._impl.install_app(apk_path)

    def uninstall_app(self, app_bundle: str):
        return self._impl.uninstall_app(app_bundle)

    def push_file(self, local_path: str, device_path: str):
        return self._impl.push_file(local_path, device_path)

    def pull_file(self, device_path: str, local_path: str):
        return self._impl.pull_file(device_path, local_path)

    def devices(self):
        return self._impl.devices()

