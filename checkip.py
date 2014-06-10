#!/usr/bin/env python
# -*- coding: utf-8 -*-
__author__ = 'moonshawdo@gamil.com'
"""
验证哪些IP可以用在gogagent中
主要是检查这个ip是否可以连通，并且证书是否为google.com
"""

import os
import sys
import threading
import socket
import ssl
import re
import select
import traceback
import logging

if sys.version_info[0] == 3:
    from queue import Queue, Empty

    try:
        from functools import reduce
    finally:
        pass
    try:
        xrange
    except NameError:
        xrange = range
else:
    from Queue import Queue, Empty
import time

g_useOpenSSL = 1
g_usegevent = 1
if g_useOpenSSL == 1:
    try:
        import OpenSSL.SSL

        SSLError = OpenSSL.SSL.WantReadError
        g_usegevent = 0
    except ImportError:
        g_useOpenSSL = 0
        SSLError = ssl.SSLError
else:
    SSLError = ssl.SSLError

if g_usegevent == 1:
    try:
        from gevent import monkey
        monkey.patch_all()
    except ImportError:
        g_usegevent = 0

g_useprocess = 5

"""
ip_str_list为需要查找的IP地址，第一组的格式：
1.xxx.xxx.xxx.xxx-xx.xxx.xxx.xxx
2.xxx.xxx.xxx.xxx/xx
3.xxx.xxx.xxx.
4 xxx.xxx.xxx.xxx

组与组之间可以用换行、'|'或','相隔开
"""
ip_str_list = '''
218.253.0.80-218.253.0.90
'''

"连接超时设置"
g_conntimeout = 5
g_handshaketimeout = 7

g_filedir = os.path.dirname(__file__)
g_cacertfile = os.path.join(g_filedir, "cacert.pem")
g_ipfile = os.path.join(g_filedir, "ip.txt")
g_ssldomain = ("google.com", "google.pk", "google.co.uk")
g_maxthreads = 378
if g_usegevent == 1:
    g_useprocess = 0
    g_maxthreads = 768
elif g_useOpenSSL == 0:
    g_maxthreads = 256
# gevent socket cnt must less than 1024
if g_usegevent == 1 and g_maxthreads > 1000:
    g_maxthreads = 768
    
if g_useprocess > 0: 
    from multiprocessing import Process,JoinableQueue as Queue,Event,Lock
else:
    from threading import Event,Lock

g_finish = Event()
g_ready = Event()

logging.basicConfig(format="[%(process)d][%(threadName)s]%(message)s",level=logging.INFO)

def PRINT(strlog):
    logging.info(strlog)
    

class TCacheResult(object):
    def __init__(self):
        self.okqueue = Queue()
        self.failipqueue = Queue()
    
    def addOKIP(self,costtime,ip,ssldomain):
        self.okqueue.put((costtime,ip,ssldomain))
        
    def addFailIP(self,ip):
        self.failipqueue.put(ip)
        if self.failipqueue.qsize() > 512:
            self.flushFailIP()        
       
    def getIPResult(self):
        return self._queuetolist(self.okqueue)
        
    def _queuetolist(self,myqueue):
        result = []
        qsize = myqueue.qsize()
        while qsize > 0:
            result.append(myqueue.get())
            qsize -= 1
        return result
    
    def flushFailIP(self):
        if self.failipqueue.qsize() > 0 :
            logging.info(";".join(self._queuetolist(self.failipqueue)) + " timeout")


class my_ssl_wrap(object):
    ssl_cxt = None
    ssl_cxt_lock = threading.Lock()

    def __init__(self):
        pass

    @staticmethod
    def initsslcxt():
        if my_ssl_wrap.ssl_cxt is not None:
            return
        try:
            my_ssl_wrap.ssl_cxt_lock.acquire()
            if my_ssl_wrap.ssl_cxt is not None:
                return
            my_ssl_wrap.ssl_cxt = OpenSSL.SSL.Context(OpenSSL.SSL.TLSv1_METHOD)
            my_ssl_wrap.ssl_cxt.set_timeout(g_handshaketimeout)
            PRINT("init ssl context ok")
        except Exception:
            raise
        finally:
            my_ssl_wrap.ssl_cxt_lock.release()

    def getssldomain(self, threadname, ip):
        time_begin = time.time()
        s = None
        c = None
        haserror = 1
        try:
            s = socket.socket()
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if g_useOpenSSL:
                my_ssl_wrap.initsslcxt()
                s.settimeout(g_conntimeout)
                s.connect((ip, 443))
                c = OpenSSL.SSL.Connection(my_ssl_wrap.ssl_cxt, s)
                c.set_connect_state()
                s.setblocking(0)
                while True:
                    try:
                        c.do_handshake()
                        break
                    except SSLError:
                        infds, outfds, errfds = select.select([s, ], [], [], g_handshaketimeout)
                        if len(infds) == 0:
                            raise SSLError("do_handshake timed out")
                        else:
                            costtime = int(time.time() - time_begin)
                            if costtime > g_handshaketimeout:
                                raise SSLError("do_handshake timed out")
                            else:
                                pass
                    except OpenSSL.SSL.SysCallError as e:
                        raise SSLError(e.args)
                cert = c.get_peer_certificate()
                time_end = time.time()
                costtime = int(time_end * 1000 - time_begin * 1000)
                for subject in cert.get_subject().get_components():
                    if subject[0] == "CN":
                        domain = subject[1]
                        PRINT("ip: %s,CN: %s " % (ip, domain))
                        haserror = 0
                        return domain, costtime
                PRINT("%s can not get CN: %s " % (ip, cert.get_subject().get_components()))
                return None, costtime
            else:
                s.settimeout(g_conntimeout)
                c = ssl.wrap_socket(s, cert_reqs=ssl.CERT_REQUIRED, ca_certs=g_cacertfile,
                                    do_handshake_on_connect=False)
                c.settimeout(g_conntimeout)
                c.connect((ip, 443))
                c.settimeout(g_handshaketimeout)
                c.do_handshake()
                cert = c.getpeercert()
                time_end = time.time()
                costtime = int(time_end * 1000 - time_begin * 1000)
                '''cert format:
                {'notAfter': 'Aug 20 00:00:00 2014 GMT', 'subjectAltName': (('DNS', 'google.com'),
                  ('DNS', 'youtubeeducation.com')),
                  'subject': ((('countryName', u'US'),), (('stateOrProvinceName', u'California'),),
                  (('localityName', u'Mountain View'),), (('organizationName', u'Google Inc'),),
                  (('commonName', u'google.com'),))
                }'''
                if 'subject' in cert:
                    subjectitems = cert['subject']
                    for mysets in subjectitems:
                        for item in mysets:
                            if item[0] == "commonName":
                                if not isinstance(item[1], str):
                                    domain = item[1].encode("utf-8")
                                else:
                                    domain = item[1]
                                PRINT("ip: %s,CN: %s " % (ip, domain))
                                haserror = 0
                                return domain, costtime
                    PRINT("%s can not get commonName: %s " % (ip, subjectitems))
                else:
                    PRINT("%s can not get subject: %s " % (ip, cert))
                return None, costtime
        except SSLError as e:
            time_end = time.time()
            costtime = int(time_end * 1000 - time_begin * 1000)
            if "timed out"  not in str(e):
                PRINT("SSL Exception(%s): %s, times:%d ms " % (ip, e, costtime))
            return None, costtime
        except IOError as e:
            time_end = time.time()
            costtime = int(time_end * 1000 - time_begin * 1000)
            if "timed out"  not in str(e):
                PRINT("Catch IO Exception(%s): %s, times:%d ms " % (ip, e, costtime))
            return None, costtime
        except Exception as e:
            time_end = time.time()
            costtime = int(time_end * 1000 - time_begin * 1000)
            PRINT("Catch Exception(%s): %s, times:%d ms " % (ip, e, costtime))
            return None, costtime
        finally:
            if g_useOpenSSL:
                if c:
                    if haserror == 0:
                        c.shutdown()
                        c.sock_shutdown(2)
                    c.close()
                if s:
                    s.close()
            else:
                if c:
                    if haserror == 0:
                        c.shutdown(2)
                    c.close()
                elif s:
                    s.close()


class Ping(threading.Thread):
    ncount = 0
    ncount_lock = threading.Lock()

    def __init__(self,checkqueue,cacheResult):
        threading.Thread.__init__(self)
        self.queue = checkqueue
        self.cacheResult = cacheResult

    def runJob(self):
        while not g_ready.is_set():
            g_ready.wait(5)
        while not g_finish.is_set() and self.queue.qsize() > 0:
            try:
                addrint = self.queue.get_nowait()
                ipaddr = to_string(addrint)
                self.queue.task_done()
                ssl_obj = my_ssl_wrap()
                (ssldomain, costtime) = ssl_obj.getssldomain(self.getName(), ipaddr)
                if ssldomain is not None and ssldomain.lower() in g_ssldomain:
                    self.cacheResult.addOKIP(costtime, ipaddr, ssldomain)
                elif ssldomain is None:
                    self.cacheResult.addFailIP(ipaddr)
            except Empty:
                break

    def run(self):
        try:
            Ping.ncount_lock.acquire()
            Ping.ncount += 1
            Ping.ncount_lock.release()
            self.runJob()
        except Exception:
            raise
        finally:
            Ping.ncount_lock.acquire()
            Ping.ncount -= 1
            Ping.ncount_lock.release()


def from_string(s):
    """Convert dotted IPv4 address to integer."""
    return reduce(lambda a, b: a << 8 | b, map(int, s.split(".")))


def to_string(ip):
    """Convert 32-bit integer to dotted IPv4 address."""
    return ".".join(map(lambda n: str(ip >> n & 0xFF), [24, 16, 8, 0]))


g_ipcheck = re.compile(r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$')


def checkipvalid(ip):
    """检查ipv4地址的合法性"""
    ret = g_ipcheck.match(ip)
    if ret is not None:
        "each item range: [0,255]"
        for item in ret.groups():
            if int(item) > 255:
                return 0
        return 1
    else:
        return 0


def splitip(strline):
    """从每组地址中分离出起始IP以及结束IP"""
    begin = ""
    end = ""
    if "-" in strline:
        "xxx.xxx.xxx.xxx-xxx.xxx.xxx.xxx"
        begin, end = strline.split("-")
    elif strline.endswith("."):
        "xxx.xxx.xxx."
        begin = strline + "0"
        end = strline + "255"
    elif "/" in strline:
        "xxx.xxx.xxx.xxx/xx"
        (ip, bits) = strline.split("/")
        if checkipvalid(ip) and (0 <= int(bits) <= 32):
            orgip = from_string(ip)
            end_bits = (1 << (32 - int(bits))) - 1
            begin_bits = 0xFFFFFFFF ^ end_bits
            begin = to_string(orgip & begin_bits)
            end = to_string(orgip | end_bits)
    else:
        "xxx.xxx.xxx.xxx"
        begin = strline
        end = strline

    return begin, end


def dumpstacks():
    code = []
    for threadId, stack in sys._current_frames().items():
        code.append("\n# Thread: %d" % (threadId))
        for filename, lineno, name, line in traceback.extract_stack(stack):
            code.append('File: "%s", line %d, in %s' % (filename, lineno, name))
            if line:
                code.append("  %s" % (line.strip()))
    sys.stderr.write("\n".join(code))
    
def checksingleprocess(ipqueue,cacheResult,max_threads):
    threadlist = []
    threading.stack_size(96 * 1024)
    qsize = ipqueue.qsize()
    maxthreads = qsize if qsize < max_threads else max_threads
    PRINT('need create max threads count: %d,total ip cnt: %d ' % (maxthreads, qsize))
    for i in xrange(1, maxthreads + 1):
        ping_thread = Ping(ipqueue,cacheResult)
        ping_thread.setDaemon(True)
        try:
            ping_thread.start()
        except threading.ThreadError as e:
            PRINT('start new thread except: %s,work thread cnt: %d' % (e, Ping.ncount))
            "can not create new thread"
            break
        threadlist.append(ping_thread)
    g_ready.set()
    try:
        time_begin = time.time()
        lastcount = Ping.ncount
        while Ping.ncount > 0:
            g_finish.wait(1)
            time_end = time.time()
            if lastcount != Ping.ncount or ipqueue.qsize() > 0:
                time_begin = time_end
                lastcount = Ping.ncount
            else:
                if time_end - time_begin > g_handshaketimeout * 3:
                    dumpstacks()
                    break;
                else:
                    time_begin = time_end
        g_finish.set()
    except KeyboardInterrupt:
        g_finish.set()
        #for thread in threadlist:
        #   thread.join()
        
def callsingleprocess(ipqueue,cacheResult,max_threads):
    PRINT("Start Process")
    checksingleprocess(ipqueue, cacheResult,max_threads)
    PRINT("End Process")
    
    
def checkmultiprocess(ipqueue,cacheResult):
    if ipqueue.qsize() == 0:
        return
    processlist = []
    "如果ip数小于512，只使用一个子进程，否则则使用指定进程数，每个进程处理平均值的数量ip"
    max_threads = g_maxthreads
    maxprocess = g_useprocess
    if ipqueue.qsize() < g_maxthreads:
        max_threads = ipqueue.qsize()
        maxprocess = 1
    else:
        max_threads = (ipqueue.qsize() + g_useprocess) / g_useprocess
    for i in xrange(0,maxprocess):
        p = Process(target=callsingleprocess,args=(ipqueue,cacheResult,max_threads))
        processlist.append(p)
        p.start()
    
    try:
        for p in processlist:
            p.join()
    except KeyboardInterrupt:
        for p in processlist:
            if p.is_alive():
                p.terminate()  


def list_ping():
    if g_useOpenSSL == 1:
        PRINT("support PyOpenSSL")
    if g_usegevent == 1:
        PRINT("support gevent")

    iprangelist = []
    checkqueue = Queue()
    cacheResult = TCacheResult()
    "split ip,check ip valid and get ip begin to end"
    iplineslist = re.split("\r|\n", ip_str_list)
    for iplines in iplineslist:
        if len(iplines) == 0 or iplines[0] == '#':
            continue
        ips = re.split(",|\|", iplines)
        for line in ips:
            if len(line) == 0 or line[0] == '#':
                continue
            begin, end = splitip(line)
            if checkipvalid(begin) == 0 or checkipvalid(end) == 0:
                PRINT("ip format is error,line:%s, begin: %s,end: %s" % (line, begin, end))
                sys.exit(1)
            nbegin = from_string(begin)
            nend = from_string(end)
            while nbegin <= nend:
                checkqueue.put(nbegin)
                nbegin += 1

    if g_useprocess == 0:
        checksingleprocess(checkqueue,cacheResult,g_maxthreads)
    else:
        checkmultiprocess(checkqueue,cacheResult)
    
    cacheResult.flushFailIP()
    ip_list = cacheResult.getIPResult()
    ip_list.sort()

    PRINT('try to collect ssl result')
    op = 'wb'
    if sys.version_info[0] == 3:
        op = 'w'
    ff = open(g_ipfile, op)
    ncount = 0
    for ip in ip_list:
        domain = ip[2]
        PRINT("[%s] %d ms,domain: %s" % (ip[1], ip[0], domain))
        if domain is not None:
            ff.write(ip[1])
            ff.write("|")
            ncount += 1
    PRINT("write to file %s ok,count:%d " % (g_ipfile, ncount))
    ff.close()


if __name__ == '__main__':
    list_ping()
