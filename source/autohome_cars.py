# encoding=utf-8
#
# 爬取https://mall.autohome.com.cn/list上的平行进口车数据, 全国数据总计5120个
#
from gevent import monkey
monkey.patch_all()

import requests
from lxml import etree
from gevent.pool import Pool
from gevent.queue import Queue
from urllib.parse import urljoin
from pymongo import MongoClient
import time
import hashlib

ORDER_NO = 'ZF201710145848mpry3V'
SECRET = '1d3a17f969724c978a36115ed39bce06'

client = MongoClient()
db = client['Market_Research']
collection = db['autohome']

# 设置Pool和Queue
pool = Pool(size=5)
list_queue = Queue()
detail_queue = Queue()
item_queue = Queue()
# 设置去重
list_set = set()

START_URL = "/list/0-999999-0-0-0-0-0-0-0-1.html?factoryId=0&minPrice=-1&maxPrice=-1&specId=0&stageTag=0&importTag=1&double11Tag=0&prefix=&dataSource=&minDownPay=&maxDownPay=&businessType=&providerId="
BASE_URL = "https://mall.autohome.com.cn"

headers = {
    'Cookie': 'UM_distinctid=15f50c9c9222c2-02ae0f49d2afbb-31657c00-384000-15f50c9c923681; fvlid=1508888921932UuGMXqGaBI; sessionip=117.15.125.251; sessionid=C30F3DFE-3553-4381-AF57-BBF39F1497C3%7C%7C2017-10-25+07%3A48%3A47.666%7C%7C0; ahpau=1; ahsids=4348; sessionuid=C30F3DFE-3553-4381-AF57-BBF39F1497C3%7C%7C2017-10-25+07%3A48%3A47.666%7C%7C0; mpvareaid=2023627; mallsfvi=1508929472012tWqpLlMq%7Cwww.autohome.com.cn%7C103414; mallslvi=103414%7Cwww.autohome.com.cn%7C1508929472012tWqpLlMq; hasGetRedPackage=0; mallCityId=999999; ahpvno=29; ref=0%7C0%7C0%7C0%7C2017-10-25+19%3A44%3A54.326%7C2017-10-25+07%3A48%3A47.666; sessionvid=6159878B-1D90-4E27-A6BE-AE4A5144CAEB; area=120199',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/61.0.3163.100 Safari/537.36',
    'Host': 'mall.autohome.com.cn',
    'Referer': 'https://mall.autohome.com.cn/list/0-999999-0-0-0-0-0-0-0-1.html?factoryId=0&minPrice=-1&maxPrice=-1&stageTag=0&importTag=1&double11Tag=0&dataSource=&eventId=&eventProcessId=&providerId=&itemIds=&eventProcessIds=&providerIds=&dataSources=&specId=0&minDownPay=&maxDownPay=&businessType=',
    'X-Requested-With': 'XMLHttpRequest',
    'Accept': '*/*',
    'Accept-Encoding': 'gzip,deflate,br',
    'Accept-Language': 'zh-CN,zh;q=0.8',
    'Upgrade-Insecure-Requests': '1'
}

proxies = {
    'http': 'http://forward.xdaili.cn:80',
    'https': 'https://forward.xdaili.cn:80'
}

def form_sign():
    timestamp = int(time.time())
    plain_text = 'orderno=%s,secret=%s,timestamp=%s' % (ORDER_NO, SECRET, timestamp)
    sign = hashlib.md5(plain_text.encode('utf-8')).hexdigest().upper()
    auth = 'sign=%s&orderno=%s&timestamp=%s' % (sign, ORDER_NO, timestamp)
    return auth


def fetch(url):
    h = headers.copy()
    h['Proxy-Authorization'] = form_sign()
    req = requests.get(urljoin(BASE_URL, url), headers=headers, timeout=10)
    if req.status_code != 200:
        print('%s:请求失败--%s' % (url, req.status_code))
        return None
    else:
        return req.text.encode('utf-8')

def crawl():
    html = fetch(START_URL)
    list_set.add(START_URL)
    if html is not None:
        tree = etree.HTML(html)
        for car in tree.xpath('//li[@class="carbox"]'):
            spec_id = ''.join(car.xpath('./a/span[@class="carbox-compare"]/@link')).strip()
            item_id = car.xpath('./@data-itemid')[0].strip()
            detail_queue.put({'spec_id': spec_id, 'item_id': item_id})

        next_page = tree.xpath('//a[@class="pager-next"]/@href')
        if len(next_page) > 0:
            next_page = next_page[0].strip()
            list_queue.put(next_page)
            time.sleep(1)

def list_loop():
    while True:
        url = list_queue.get()
        if url not in list_set:
            pool.spawn(crawl_list_page, url)

def crawl_list_page(url):
    if url in list_set:
        return
    html = fetch(url)
    if html is not None:
        tree = etree.HTML(html)
        for car in tree.xpath('//li[@class="carbox"]'):
            spec_id = ''.join(car.xpath('./a/span[@class="carbox-compare"]/@link')).strip()
            item_id = car.xpath('./@data-itemid')[0].strip()
            detail_queue.put({'spec_id': spec_id, 'item_id': item_id})
        next_page = tree.xpath('//a[@class="pager-next"]/@href')
        if len(next_page) > 0:
            next_page = next_page[0].strip()
            list_queue.put(next_page)
            time.sleep(1)

def detail_loop():
    while True:
        car_info = detail_queue.get()
        pool.spawn(crawl_detail_page, car_info)

def crawl_detail_page(car_info):
    """
    URL: /http/data.html
    PARAMS: data[_host]=//api.admin.mall.m6.autohome.com.cn/tradespec/getParameters.jtml
    PARAMS: data[_appid]=mall
    PARAMS: data[specid]=<specid>
    RET: {'returncode', 'message', 'result':{'specid', 'paramtypeitems': [{id, name, pordercls, paramitems}]}}
    车型名称, 厂商指导价(元), 厂商, 级别, 发动机, 价格
    """
    url = 'https://mall.autohome.com.cn/detail/getItemsDetail.html?itemIds=%s' % car_info['item_id']
    req = requests.get(url, headers=headers, timeout=10)
    if req.status_code != 200:
        print('%s:请求失败!' % url)
    results = req.json()['data']
    car_info['price'] = results[0]['price']
    car_info['brand'] = results[0]['brandName']
    car_info['official_price'] = results[0]['productPrice']
    time.sleep(1)

    url = urljoin(BASE_URL, '/http/data.html')
    params = {
        'data[_host]': '//api.admin.mall.m6.autohome.com.cn/tradespec/getParameters.jtml',
        'data[_appid]': 'mall',
        'data[specid]': car_info['spec_id']
    }
    h = headers.copy()
    h['Proxy-Authorization'] = form_sign()
    req = requests.get(url, params=params, headers=headers, timeout=10)
    if req.status_code != 200:
        print('%s:请求失败!' % car_info['spec_id'])
        return
    result = req.json()['result']['paramtypeitems'][0]['paramitems']
    for param in result:
        if param['name'] == '车型名称':
            car_info['name'] = param['value']
        elif param['name'] == '级别':
            car_info['level'] = param['value']
        elif param['name'] == '发动机':
            car_info['engine'] = param['value']

    item_queue.put(car_info)
    time.sleep(2)

def db_loop():
    while True:
        car = item_queue.get()
        car_id = collection.insert_one(car).inserted_id
        print("%s: %s" %(car_id, car['spec_id']))
        print(car)


if __name__ == '__main__':
    crawl()
    pool.spawn(list_loop)
    pool.spawn(detail_loop)
    pool.spawn(db_loop)
    pool.join()
