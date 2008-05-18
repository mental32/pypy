from pypy.lang.smalltalk import model
from pypy.lang.smalltalk import utility

class Wrapper(object):
    def __init__(self, w_self):
        assert isinstance(w_self, model.W_PointersObject)
        self.w_self = w_self

    def read(self, index0):
        try:
            return self.w_self._vars[index0]
        except IndexError:
            # XXX nicer errormessage
            raise

    def write(self, index0, w_new):
        try:
            self.w_self._vars[index0] = w_new
        except IndexError:
            # XXX nicer errormessage
            raise

def make_getter(index0):
    def getter(self):
        return self.read(index0)
    return getter

def make_setter(index0):
    def setter(self, w_new):
        return self.write(index0, w_new)
    return setter

def make_getter_setter(index0):
    return make_getter(index0), make_setter(index0)
    
class LinkWrapper(Wrapper):
    next_link, store_next_link = make_getter_setter(0)

class ProcessWrapper(LinkWrapper):
    suspended_context, store_suspended_context = make_getter_setter(1)
    priority = make_getter(2)
    my_list, store_my_list = make_getter_setter(3)

    def put_to_sleep(self):
        sched = scheduler()
        priority = self.priority()
        process_list = sched.get_process_list(priority)
        process_list.add_process(self.w_self)

    def activate(self, interp):
        from pypy.lang.smalltalk import objtable
        sched = scheduler()
        w_old_process = sched.active_process()
        sched.store_active_process(self.w_self)
        ProcessWrapper(w_old_process).store_suspended_context(interp.w_active_context())
        interp.store_w_active_context(self.suspended_context())
        self.store_suspended_context(objtable.w_nil)

    def resume(self, interp):
        sched = scheduler()
        active_process = ProcessWrapper(sched.active_process())
        active_priority = active_process.priority()
        priority = self.priority()
        if priority > active_priority:
            active_process.put_to_sleep()
            self.activate(interp)
        else:
            self.put_to_sleep(process)


class LinkedListWrapper(Wrapper):
    first_link, store_first_link = make_getter_setter(0)
    last_link, store_last_link = make_getter_setter(1)

    def is_empty_list(self):
        from pypy.lang.smalltalk import objtable
        return self.first_link() is objtable.w_nil

    def add_last_link(self, w_object):
        if self.is_empty_list():
            self.store_first_link(w_object)
        else:
            LinkWrapper(self.last_link()).store_next_link(w_object)
        self.store_last_link(w_object)

    def remove_first_link_of_list(self):
        from pypy.lang.smalltalk import objtable
        w_first = self.first_link()
        w_last = self.last_link()
        if w_first is w_last:
            self.store_first_link(objtable.w_nil)
            self.store_last_link(objtable.w_nil)
        else:
            w_next = LinkWrapper(w_first).next_link()
            self.store_first_link(w_next)
        LinkWrapper(w_first).store_next_link(objtable.w_nil)
        return w_first

class ProcessListWrapper(LinkedListWrapper):
    def add_process(self, w_process):
        self.add_last_link(w_process)
        ProcessWrapper(w_process).store_my_list(self.w_self)

class AssociationWrapper(Wrapper):
    key = make_getter(0)
    value, store_value = make_getter_setter(1)

class SchedulerWrapper(Wrapper):
    priority_list = make_getter(0)
    active_process, store_active_process = make_getter_setter(1)
    
    def get_process_list(self, w_priority):
        priority = utility.unwrap_int(w_priority)
        lists = self.priority_list()
        return ProcessListWrapper(Wrapper(lists).read(priority))

def scheduler():
    from pypy.lang.smalltalk import objtable
    w_association = objtable.objtable["w_schedulerassociationpointer"]
    assert w_association is not None
    w_scheduler = AssociationWrapper(w_association).value()
    assert isinstance(w_scheduler, model.W_PointersObject)
    return SchedulerWrapper(w_scheduler)

class SemaphoreWrapper(LinkedListWrapper):

    excess_signals, store_excess_signals = make_getter_setter(0)

    def signal(self, interp):
        if self.is_empty_list():
            w_value = self.excess_signals()
            w_value = utility.wrap_int(utility.unwrap_int(w_value) + 1)
            self.store_excess_signals(w_value)
        else:
            self.resume(self.remove_first_link_of_list(), interp)

    def wait(self, w_process, interp):
        excess = utility.unwrap_int(self.excess_signals())
        if excess > 0:
            w_excess = utility.wrap_int(excess - 1)
            self.store_excess_signals(w_excess)
        else:
            self.add_last_link(w_process)
            ProcessWrapper(w_process).put_to_sleep()
