from logging import getLogger


def get_log(name: str = ''):
    return getLogger(f'AndroidPerf{name and f":{name}" or ""}')


default = get_log()
