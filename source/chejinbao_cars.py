# encoding=utf-8
#
# 抓取车金宝(http://www.chejinbao.cn)上关于平行进口车的车型和价格,
# 用于对比国内经销商的车型和价格
#
from gevent import monkey
monkey.patch_all()
import requests
from lxml import etree
from gevent.pool import Pool
from gevent.queue import Queue
import pymongo

START_URL = 'online.html?brandID=&seriesID=&startprice=&endprice=&model=&emissions=0&version=&saleType=&year=&provinceID=&cityID=&orderByType=&page=%s'
BASE_URL = 'http://www.chejinbao.cn/cars/'

page_set = set()

pool = Pool(size=10)
list_queue = Queue()
detail_queue = Queue()
item_queue = Queue()

client = pymongo.MongoClient()
db = client['Market_Research']
collection = db['chejinbao_cars']

HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Accept-Encoding': 'gzip, deflate',
    'Accept-Language': 'zh-CN,zh;q=0.8',
    'Host': 'www.chejinbao.cn',
    'Upgrade-Insecure-Requests': '1',
    'User-Agent': 'Mozilla/5.0 (compatible, MSIE 11, Windows NT 6.3; Trident/7.0;  rv:11.0) like Gecko',
    'Cookie': 'Hm_lvt_f605046808ea42a8f3df51b56641ab7d=1508816779; Hm_lpvt_f605046808ea42a8f3df51b56641ab7d=1508816779; __root_domain_v=.chejinbao.cn; _qddaz=QD.orbb3v.bctxtv.j952jxis; LXB_REFER=www.google.com; UM_distinctid=15f4c7f43cc87f-050fcd801a322-31637c01-1fa400-15f4c7f43cfb38; JSESSIONID=95644C5123E0172EAB7279E98B054555; _qdda=3-1.10ga5x; _qddab=3-wo4ra4.j95ci7p6; CNZZDATA1260972416=1067066284-1508816929-null%7C1508830980'
}

def crawl():
    for i in range(1, 17):
        list_queue.put(START_URL % i)

def list_loop():
    while True:
        link = list_queue.get()
        pool.spawn(crawl_list_page, link)

def detail_loop():
    while True:
        link = detail_queue.get()
        pool.spawn(crawl_detail_page, link)

def item_loop():
    while True:
        item = item_queue.get()
        car_id = collection.insert_one(item).inserted_id
        print('%s: %s' % (car_id, item['chejinbao_id']))

def crawl_list_page(url):
    """
    使用page_set进行去重
    """
    if url in page_set:
        return
    else:
        page_set.add(url)
        url = BASE_URL + url
        req = requests.get(url, headers=HEADERS)
        if req.status_code != 200:
            print('%s 请求失败: %s!' % (url, req.status_code))
            return
        tree = etree.HTML(req.text.encode('utf-8'))
        links = tree.xpath('//div[@class="dimension"]/a/@href')
        for link in links:
            detail_queue.put(link)

def crawl_detail_page(url):
    """
    抓取详情页面, 只需要提取一些特殊数据进行对比分析即可
    品牌, 车名, 排量, 价格区间, 现车/期车, 版本, 车型
    """
    chejinbao_id = url.replace('.html', '')
    url = BASE_URL + url
    req = requests.get(url, headers=HEADERS)
    if req.status_code != 200:
        print('%s 请求失败: %s!' % (url, req.status_code))
        return
    tree = etree.HTML(req.text.encode('utf-8'))
    # 解析品牌, 车名和排量
    name = ''.join(tree.xpath('//span[@id="title"]/text()')).strip()
    displacement = tree.xpath('//div[@class="details"]/em[2]/text()')[0].strip()
    displacement = displacement.replace(' ', '').replace('\n', '').replace('\t', '').replace('\r', '')[3:]
    # 获取价格区间
    price = ''.join(tree.xpath('//span[@id="carPrice"]/text()')).strip()
    price = price.replace(' ','').replace('\n', '').replace('\t', '').replace('\r', '')
    # 现车/期车
    sale_type = tree.xpath('//span[@id="saleType"]/text()')[0].strip()
    # 规格
    version = tree.xpath('//span[@id="version"]/text()')[0].strip()
    # 燃油类型
    fuel_type = tree.xpath('//span[@id="engine_fuel_type"]/text()')[0].strip()[5:]
    # 级别: SUV等
    model = tree.xpath('//span[@id="base_level"]/text()')[0].strip()[3:]
    car = {
        'name': name,
        'displacement': displacement,
        'price': price,
        'sale_type': sale_type,
        'version': version,
        'fuel_type': fuel_type,
        'model': model,
        'chejinbao_id': chejinbao_id
    }
    item_queue.put(car)


if __name__ == '__main__':
    crawl()
    pool.spawn(list_loop)
    pool.spawn(detail_loop)
    pool.spawn(item_loop)
    pool.join()
