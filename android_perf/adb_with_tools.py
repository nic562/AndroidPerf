# coding=utf8
import time
from urllib.parse import urlencode

from .base_adb import AdbProxy
from .app_info import AppInfo
from .log import default as logging


class AdbProxyWithTools(AdbProxy):
    """附带一些额外Android工具操作api"""

    TOOLS_APP = AppInfo().simple(
        'Screen Recorder (测试工具)',
        'io.github.nic562.screen.recorder',
        run_args='.MainActivity',
        description='请到 [https://github.com/nic562/AndroidScreenRecorder] 下载所需工具App.'
                    '\n如果自动化运行过程中遇到问题，请检查App的授权情况，例如【通知权限】、【创建VPN权限】、【存储空间权限】等'
    )

    def _get_tools_app_start_cmd(self):
        return f'am start -n {self.TOOLS_APP.pkg}/{self.TOOLS_APP.run_args} '

    def send_broadcast_2tools_app(self, **kv: str):
        self.check_tools_app()
        return self.send_broadcast(
            f'{self.TOOLS_APP.pkg}.RemoteCallingSV',
            f'-n {self.TOOLS_APP.pkg}/.RemoteCallingReceiver',
            **kv
        )

    def check_tools_app(self) -> bool:
        """
        监测是否已经安装目标应用
        :return:
        """
        if self.TOOLS_APP.version:
            return True
        self.TOOLS_APP.version = self.get_app_version(self.TOOLS_APP.pkg)
        rs = bool(self.TOOLS_APP.version)
        if not rs:
            raise EnvironmentError(self.TOOLS_APP.description)

    def start_tools_app(self):
        self.check_tools_app()
        return self.start_app(self.TOOLS_APP)

    def kill_tools_app(self):
        return self.kill_app(self.TOOLS_APP.pkg)

    def close(self, kill_tools=True):
        if kill_tools:
            self.kill_tools_app()
        super().close()


class AdbProxyWithScreenRecorder(AdbProxyWithTools):
    """附带录屏并将视频上传到指定服务器地址的api"""

    def update_screen_record_settings(self, auto_stop_record: bool = True,
                                      record_auto2back: bool = True,
                                      record_count_down_second: int = 5,
                                      record_auto_delete: bool = False):
        logging.info(f'修改录屏工具配置:\n自动停止结束录屏【{auto_stop_record}】\n录屏倒数【{record_count_down_second}】'
                     f'\n录屏自动切到后台【{record_auto2back}】'
                     f'\n录屏视频上传完毕自动删除【{record_auto_delete}】')
        rs = self.run_shell(f'{self._get_tools_app_start_cmd()}'
                            f'--es setting 1 --ez auto_2back {str(record_auto2back).lower()} '
                            f'--ez auto_stop_record {str(auto_stop_record).lower()} '
                            f'--ei record_count_down_second {record_count_down_second} '
                            f'--ez record_auto_delete {str(record_auto_delete).lower()} ')
        if rs.find('Starting:') == -1:
            raise RuntimeError(f'修改录屏设置异常：`{rs}`')

    def start_screen_record(self, key: str = None):
        """
        开启录屏
        :param key: 必须保证每次录屏采用不同的key，默认为None 则会自动生成。自定义的话，可以在后期进行筛查
        :return:
        """
        rs = self.run_shell(f'{self._get_tools_app_start_cmd()} --es ui startRecord --es key {key}')
        if rs.find('Starting:') == -1:
            raise RuntimeError(f'启动录屏异常：`{rs}`')

    def stop_screen_record(self):
        """
        停止录屏。执行本方法后，记得预留一定时间(至少1秒)保证指令在工具App中正确执行以保存录屏视频文件，不要马上kill掉工具 (见 close方法)
        :return:
        """
        rs = self.run_shell(f'{self._get_tools_app_start_cmd()} --es ui stopRecording')
        if rs.find('Starting:') == -1:
            raise RuntimeError(f'停止录屏异常：`{rs}`')

    def set_screen_record_upload_api(self, title: str, url: str, method: str, upload_file_arg_name: str,
                                     headers: dict = None, body: dict = None, body_need_encoding=False):
        """
        设置录屏视频上传接口
        :param title: 标题，唯一标识，可用于执行上传录屏视频时指定特定接口
        :param url: 上传接口地址
        :param method: 上传接口请求方式
        :param upload_file_arg_name: 上传文件的http Form 中的文件参数名
        :param headers: 请求头，可选
        :param body: 请求体，可选，内部可用占位参数值：$create_time
        :param body_need_encoding: 是否对body 进行编码，可选，默认：否
        """
        hds = f'--es header {urlencode(headers)}'.replace("&", r"\&") if headers else ''
        bds = f'--es body {urlencode(body)}'.replace("&", r"\&") if body else ''
        cmd = (f'{self._get_tools_app_start_cmd()} --es data api '
               f'--es title {title} --es url {url} --es method {method} '
               f'--es uploadFileArgName {upload_file_arg_name} '
               f'--ez isBodyEncoding {str(body_need_encoding).lower()} {hds} {bds}')
        rs = self.run_shell(cmd)
        if rs.find('Starting:') == -1:
            raise RuntimeError(f'设置上传接口异常：`{rs}`')

    def notify_to_upload_screen_record(self, api_title: str, *video_keys: str):
        rs = self.run_shell(f'{self._get_tools_app_start_cmd()} --es data upload '
                            f'--es apiTitle {api_title} '
                            f'--es videoKeys {",".join(video_keys)}')
        if rs.find('Starting:') == -1:
            raise RuntimeError(f'通知执行上传异常：`{rs}`')


class AdbProxyWithTrafficStatistics(AdbProxyWithTools):
    """如果通过Android原生文件获取流量失败，可以试试工具库中的流量统计工具"""
    NET_TRAFFIC_LOG_PATH = '/sdcard/tmp/mm.log'

    def prepare_statistics_net_traffic(self, save2file: str = NET_TRAFFIC_LOG_PATH):
        self.kill_tools_app()
        try:
            self.del_file(save2file)
        except:
            pass
        self.start_tools_app()
        while True:
            if self.find_processes(self.TOOLS_APP.pkg):
                break
            time.sleep(0.1)

    def start_statistics_net_traffic(self, app: AppInfo, save2file: str = NET_TRAFFIC_LOG_PATH):
        return self.send_broadcast_2tools_app(
            app=app.pkg,
            action='startNetTrafficStatistics',
            save2File=save2file
        )

    def stop_statistics_net_traffic(self):
        return self.send_broadcast_2tools_app(
            action='stopNetTrafficStatistics'
        )

    def prepare_and_start_statistics_net_traffic(self, app: AppInfo, save2file: str = NET_TRAFFIC_LOG_PATH):
        self.prepare_statistics_net_traffic(save2file)
        self.start_statistics_net_traffic(app, save2file)

    def read_current_net_traffic(self, save2file: str = NET_TRAFFIC_LOG_PATH) -> list:
        return self.format_net_traffic_log(self.cat_file(save2file))

    def finish_statistics_net_traffic(self, save2file: str = NET_TRAFFIC_LOG_PATH) -> str:
        self.stop_statistics_net_traffic()
        time.sleep(0.1)
        rs = self.cat_file(save2file)
        self.del_file(save2file)
        self.kill_tools_app()
        if rs.rfind('No such file or directory') != -1:
            raise ValueError(f'流量日志记录文件访问异常，请确保该【{self.TOOLS_APP.name}】已经授权VPN权限、且开启文件权限。'
                             f'例如：进入【{self.TOOLS_APP.name}】 -> 【网络统计】 -> '
                             f'【授权日志文件】 -> 找到【{self.TOOLS_APP.name}】 -> 【授予所有文件的管理权限】 -> 返回 -> '
                             f'【开启网络流量统计】 -> 【允许通知】 -> 【允许创建VPN连接】')
        time.sleep(0.1)
        return rs

    def finish2format_statistics_net_traffic(self, save2file: str = NET_TRAFFIC_LOG_PATH) -> list:
        rs = self.finish_statistics_net_traffic(save2file)
        logging.debug(f'Read File[{save2file}] result:\n{rs}')
        return self.format_net_traffic_log(rs)

    @staticmethod
    def format_net_traffic_log(s: str) -> list:
        out = []
        for x in s.split('\n'):
            if not x:
                continue
            info = x.split('\t')
            out.append(dict(second=int(info[0]), down=int(info[1]), up=int(info[2])))
        return out

    def _sync_net_traffic_statistics(self, app: AppInfo, wait_seconds=10) -> str:
        """
        自动完成一次目标App的流量采集，过程包括启动监测工具，目标App，关闭监测工具，关闭目标App
        :param app: 目标App
        :param wait_seconds: 抓取时长，秒
        :return: 返回监测工具输出日志
        # 获取结果格式,每行为1秒内的数据:
        # 第N秒\t下载字节数\t上传字节数
        """
        self.kill_by_app(app)
        self.prepare_and_start_statistics_net_traffic(app)
        time.sleep(0.1)
        self.start_app(app)
        time.sleep(wait_seconds)
        rs = self.finish_statistics_net_traffic()
        self.kill_by_app(app)
        return rs

    def sync_net_traffic_statistics(self, app: AppInfo, wait_seconds=10) -> list:
        """
        返回流量统计，单位：字节
        :param app: 目标监听App信息
        :param wait_seconds: 抓取时长，秒
        :return: [{second: x, down: n, up: n}, ...]
        """
        rs = self._sync_net_traffic_statistics(app, wait_seconds)
        return self.format_net_traffic_log(rs)


class AdbProxyWithToolsAll(AdbProxyWithScreenRecorder, AdbProxyWithTrafficStatistics):
    pass
