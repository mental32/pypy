
""" xmlhttp support
"""

from pypy.rpython.ootypesystem.bltregistry import BasicExternal, MethodDesc
from pypy.rpython.ootypesystem.ootype import String, Signed, StaticMethod, Bool, Void

import types

class XMLHttpRequest(BasicExternal):
    _fields = {
        'readyState' : 3,
        'responseText': "",
    }
    
    _methods = {
        'open' : MethodDesc(("", "", False), None),
        'send' : MethodDesc((None,), None),
#        'send_finish' : ((), None),
        #'onreadystatechange' : ([], Void),
    }
    
    #_method_mapping = {
    #    # this is neede because we've got some method duplications
    #    'send_finish' : 'send'
    #}

##class XMLHttpRequest(object):
##    _rpython_hints = {'_suggested_external' : True}
##    def __init__(self):
##        self.readyState = 0
##        
##    def open(self, method, path, flag):
##        pass
##
##    def send(self, sth):
##        pass
##    
##def get_request():
##    return XMLHttpRequest()
##
##def do_nothing():
##    pass
##
##def xmlSetCallback(func, xml):
##    # scheduler call, but we don't want to mess with threads right now
##    if one() == 0:
##        xmlSetCallback(do_nothing, xml)
##    else:
##        func()
##
##xmlSetCallback.suggested_primitive = True
