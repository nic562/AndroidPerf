# coding=utf8
# 基于whistle代理插件（https://github.com/nic562/whistle.statistics）的http请求统计
from urllib import request


def _call_proxy_request(whistle_address: str, uri, data: str = None):
    resp = request.urlopen(f'http://{whistle_address}{uri}', data=data and data.encode('utf8') or None, timeout=10)
    body = resp.read().decode('utf8')
    if resp.status == 200:
        return True, body
    return False, body


def active_statistics_status(whistle_address: str, active: bool = True):
    return _call_proxy_request(whistle_address, '/plugin.statistics/cgi-bin/active', f'active={active and 1 or 0}')


def update_statistics_settings(whistle_address: str, upload_settings: str, auto_stop=True, timeout=10):
    # 开启自动关闭
    return _call_proxy_request(whistle_address, '/plugin.statistics/cgi-bin/set-settings',
                               f'autoStop={auto_stop and 1 or 0}&timeout={timeout}&uploadArgs={upload_settings}')
