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

client = MongoClient()
db = client['Market_Research']
collection = db['autohome']

# 设置Pool和Queue
pool = Pool(size=10)
list_queue = Queue()
detail_queue = Queue()
item_queue = Queue()
# 设置去重
list_set = set()

START_URL = "/list/0-999999-0-0-0-0-0-0-0-1.html?factoryId=0&minPrice=-1&maxPrice=-1&specId=0&stageTag=0&importTag=1&double11Tag=0&prefix=&dataSource=&minDownPay=&maxDownPay=&businessType=&providerId="
BASE_URL = "https://mall.autohome.com.cn"

headers = {
    'Cookie': 'sessionid=7998F0BB-1D51-EC57-FA22-6D0D9D1CCFE6%7C%7C2016-01-10+10%3A49%3A58.174%7C%7Cwww.google.com; fvlid=1467993576377O8YaFrge; WarningClose=1; UM_distinctid=15e3cb23a862c-09011349eddaac-143a6d54-1aeaa0-15e3cb23a87bf5; historybbsName4=c-588%7C%E5%A5%94%E9%A9%B0C%E7%BA%A7; cityId=110100; cookieCityId=120100; ahpau=1; nologinid-voteid=636185841200229140; PraiseKey=4032c70a-54db-4192-867b-eeedec08397e; __utma=1.516336464.1452394200.1468077953.1506872540.15; __utmc=1; __utmz=1.1506872540.15.1.utmcsr=autohome.com.cn|utmccn=(referral)|utmcmd=referral|utmcct=/3294/; mallsfvi=1506902163496A8cMwZ8i%7Cwww.autohome.com.cn%7C2018267; product_compare=27363%2C27364; ahsids=703_162_415_264_95_4175; sessionip=111.160.31.234; wwwjbtab=0%2C0; sessionuid=7998F0BB-1D51-EC57-FA22-6D0D9D1CCFE6%7C%7C2016-01-10+10%3A49%3A58.174%7C%7Cwww.google.com; mpvareaid=2018223; mallslvi=2018223%7C0%7C1508909609247Xqluq0fw; hasGetRedPackage=0; mallCityId=999999; ahpvno=41; ref=www.google.com%7C0%7C0%7C0%7C2017-10-25+13%3A35%3A48.316%7C2017-10-25+11%3A46%3A38.483; sessionvid=FF4C43FD-71D0-419D-8083-C80AB1C41DEC; area=120199; ahrlid=1508909744864n4NNbE6K-1508909755006',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/61.0.3163.100 Safari/537.36',
    'Host': 'mall.autohome.com.cn',
    'Referer': 'https://mall.autohome.com.cn/list/0-120100-0-0-0-0-0-0-0-1.html?factoryId=0&minPrice=-1&maxPrice=-1&specId=0&stageTag=0&importTag=1&double11Tag=0&prefix=&dataSource=&minDownPay=&maxDownPay=&businessType=&providerId=',
    'X-Requested-With': 'XMLHttpRequest',
    'Accept': '*/*',
    'Accept-Encoding': 'gzip,deflate,br',
    'Accept-Language': 'zh-CN,zh;q=0.8',
    'Upgrade-Insecure-Requests': '1'
}

def fetch(url):
    req = requests.get(urljoin(BASE_URL, url), headers=headers, verify=False)
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
            price = ''.join(car.xpath('./a/div[@class="carbox-info"]/span/text()')).strip()
            item_id = car.xpath('./@data-itemid')[0].strip()
            detail_queue.put({'spec_id': spec_id, 'price': price, 'item_id': item_id})

        for page in tree.xpath('//span[@class="pager-pageindex"]/a/@href'):
            list_queue.put(page)

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
            price = ''.join(car.xpath('./a/div[@class="carbox-info"]/span/text()')).strip()
            item_id = car.xpath('./@data-itemid')[0].strip()
            detail_queue.put({'spec_id': spec_id, 'price': price, 'item_id': item_id})
        for page in tree.xpath('//span[@class="pager-pageindex"]/a/@href'):
            list_queue.put(page)

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
    url = urljoin(BASE_URL, '/http/data.html')
    params = {
        'data[_host]': '//api.admin.mall.m6.autohome.com.cn/tradespec/getParameters.jtml',
        'data[_appid]': 'mall',
        'data[specid]': car_info['spec_id']
    }
    req = requests.get(url, params=params, headers=headers)
    if req.status_code != 200:
        print('%s:请求失败!' % car_info['spec_id'])
        return
    result = req.json()['result']['paramtypeitems'][0]['paramitems']
    for param in result:
        if param['name'] == '车型名称':
            car_info['name'] = param['value']
        elif param['name'] == '厂商指导价(元)':
            car_info['official_price'] = param['value']
        elif param['name'] == '厂商':
            car_info['brand'] = param['value']
        elif param['name'] == '级别':
            car_info['level'] = param['value']
        elif param['name'] == '发动机':
            car_info['engine'] = param['value']

    item_queue.put(car_info)

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
