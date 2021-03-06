'''
Objects for parsing a list of HTTPFlows into data suitable for writing to a
HAR file.
'''

from datetime import datetime
from pcaputil import ms_from_timedelta, ms_from_dpkt_time

class Page:
    '''
    Represents a page entry in the HAR. Requests refer to one by its url.
    '''
    def __init__(self, url, title, startedDateTime):
        self.title = title
        self.startedDateTime = startedDateTime # python datetime
        self.url = url

class Entry:
    '''
    represents an HTTP request/response in a form suitable for writing to a HAR
    file.
    Members:
    * request = http.Request
    * response = http.Response
    * page_ref = string
    * startedDateTime = python datetime
    * total_time = from sending of request to end of response, milliseconds
    * time_blocked
    * time_dnsing
    * time_connecting
    * time_sending
    * time_waiting
    * time_receiving
    '''
    def __init__(self, request, response):
        self.request = request
        self.response = response
        self.page_ref = ''
        self.ts_start = int(request.ts_connect*1000)
        self.startedDateTime = datetime.fromtimestamp(request.ts_connect)
        endedDateTime = datetime.fromtimestamp(response.ts_end)
        self.total_time = ms_from_timedelta(
            endedDateTime - self.startedDateTime # plus connection time, someday
        )
        # calculate other timings
        self.time_blocked = -1
        self.time_dnsing = -1
        self.time_connecting = ms_from_dpkt_time(request.ts_start -
                                                 request.ts_connect)
        self.time_sending = \
            ms_from_dpkt_time(request.ts_end - request.ts_start)
        self.time_waiting = \
            ms_from_dpkt_time(response.ts_start - request.ts_end)
        self.time_receiving = \
            ms_from_dpkt_time(response.ts_end - response.ts_start)
        # check if timing calculations are consistent
        if self.time_sending + self.time_waiting + self.time_receiving != self.total_time:
            pass
    def json_repr(self):
        '''
        return a JSON serializable python object representation of self.
        '''
        return {
            'pageref': self.page_ref,
            'startedDateTime': self.startedDateTime.isoformat() + 'Z', # assume time is in UTC
            'time': self.total_time,
            'request': self.request,
            'response': self.response,
            'timings': {
                'blocked': self.time_blocked,
                'dns': self.time_dnsing,
                'connect': self.time_connecting,
                'send': self.time_sending,
                'wait': self.time_waiting,
                'receive': self.time_receiving
            },
            'cache': {},
        }

class UserAgentTracker(object):
    '''
    Keeps track of how many uses each user-agent header receives, and provides
    a function for finding the most-used one.
    '''
    def __init__(self):
        self.data = {} # {user-agent string: number of uses}
    def add(self, ua_string):
        '''
        Either increments the use-count for the user-agent string, or creates a
        new entry. Call this for each user-agent header encountered.
        '''
        if ua_string in self.data:
            self.data[ua_string] += 1
        else:
            self.data[ua_string] = 1
    def dominant_user_agent(self):
        '''
        Returns the agent string with the most uses.
        '''
        if not len(self.data):
            return None
        elif len(self.data) == 1:
            return self.data.keys()[0]
        else:
            # return the string from the key-value pair with the biggest value
            return max(self.data.iteritems(), key=lambda v: v[1])[0]

def page2title(page):
    return page

class PageTracker(object):
    def __init__(self):
        self.pages = dict() # {page: [ref_string, start_time, title]}

    def getref(self, page, start_time):
        if page not in self.pages:
            idx = len(self.pages)
            self.pages[page] = ['pageref_%d'%(idx), start_time, page2title(page)]
        else:
            if self.pages[page][1] > start_time:
                self.pages[page][1] = start_time
        return self.pages[page][0]

    def json_repr(self):
        '''
        return a JSON serializable python object representation of self.
        '''
        srt = sorted([(s,r,t,l) for s,(r,t,l) in self.pages.items()], key=lambda x: x[2])
        return [{
            'startedDateTime': start_time.isoformat() + 'Z', # assume time is in UTC
            'id': page_ref,
            'title': title if title != '' else 'top',
            'pageTimings': {}
            } for page_str, page_ref, start_time, title in srt]

class HTTPSession(object):
    '''
    Represents all http traffic from within a pcap.

    Members:
    * user_agents = UserAgentTracker
    * user_agent = most-used user-agent in the flow
    * entries = [Entry], all http request/response pairs
    '''
    def __init__(self, messages):
        '''
        Parses http.MessagePairs to get http info out, in preparation for
        writing it to a HAR file.
        '''
        # set-up
        self.user_agents = UserAgentTracker()
        self.page_tracker = PageTracker()
        self.entries = []
        by_ref = {}
        # iter through messages
        for msg in messages:
            # if msg.request has a user-agent, add it to our list
            entry = Entry(msg.request, msg.response)

            if 'user-agent' in msg.request.msg.headers:
                self.user_agents.add(msg.request.msg.headers['user-agent'])

            # if msg.request has a referer, keep track of that, too
            entry.page_ref = self.page_tracker.getref(msg.request.msg.headers.get('referer', ''), entry.startedDateTime)

            # parse basic data in the pair, add it to the list
            self.entries.append(entry)

        # Sort the entries on start
        self.entries.sort(lambda x,y: int(x.ts_start - y.ts_start))
        self.user_agent = self.user_agents.dominant_user_agent()
    def json_repr(self):
        '''
        return a JSON serializable python object representation of self.
        '''
        return {
            'log': {
                'version' : '1.1',
                'creator': {
                    'name': 'pcap2har',
                    'version': '0.1'
                },
                'browser': {
                    'name': self.user_agent,
                    'version': 'mumble'
                },
                'pages': self.page_tracker,
                'entries': sorted(self.entries, key=lambda x: x.ts_start)
            }
        }
