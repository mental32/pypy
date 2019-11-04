"""dict implementation specialized for object loaded by the _pypyjson module.

Somewhat similar to MapDictStrategy, also uses a map.
"""

from rpython.rlib import jit, rerased, objectmodel, debug

from pypy.objspace.std.dictmultiobject import (
    UnicodeDictStrategy, DictStrategy,
    create_iterator_classes, W_DictObject)
from pypy.interpreter.error import oefmt

def from_values_and_jsonmap(space, values_w, jsonmap):
    debug.make_sure_not_resized(values_w)
    strategy = jsonmap.strategy_instance
    if strategy is None:
        jsonmap.strategy_instance = strategy = JsonDictStrategy(space, jsonmap)
    if not objectmodel.we_are_translated():
        assert len(values_w) == len(strategy.get_keys_in_order())
        assert len(values_w) != 0
    storage = strategy.erase(values_w)
    return W_DictObject(space, strategy, storage)

def from_values_and_jsonmap_checked(space, values_w, jsonmap):
    debug.make_sure_not_resized(values_w)
    strategy = jsonmap.strategy_instance
    if strategy is None:
        jsonmap.strategy_instance = strategy = JsonDictStrategy(space, jsonmap)
    keys_w = strategy.get_keys_in_order()
    if len(values_w) != len(keys_w):
        raise oefmt(space.w_ValueError, "expected %s values, got %s", str(len(keys_w)), str(len(values_w)))
    storage = strategy.erase(values_w)
    return W_DictObject(space, strategy, storage)

def devolve_jsonmap_dict(w_dict):
    assert isinstance(w_dict, W_DictObject)
    strategy = w_dict.get_strategy()
    assert isinstance(strategy, JsonDictStrategy)
    strategy.switch_to_unicode_strategy(w_dict)

def get_jsonmap_from_dict(w_dict):
    assert isinstance(w_dict, W_DictObject)
    strategy = w_dict.get_strategy()
    assert isinstance(strategy, JsonDictStrategy)
    return strategy.jsonmap

class JsonDictStrategy(DictStrategy):
    erase, unerase = rerased.new_erasing_pair("jsondict")
    erase = staticmethod(erase)
    unerase = staticmethod(unerase)

    _immutable_fields_ = ['jsonmap']

    def __init__(self, space, jsonmap):
        DictStrategy.__init__(self, space)
        self.jsonmap = jsonmap

        self.key_to_index = None
        self.keys_in_order = None

    def wrap(self, w_key):
        return w_key

    def wrapkey(space, key):
        return key

    def get_empty_storage(self):
        raise NotImplementedError("should not be reachable")

    def is_correct_type(self, w_obj):
        space = self.space
        # This is a bit of a hack (but probably a good one): when the state of
        # our jsonmap is blocked, we consider nothing to match type-wise. That
        # way we use the code paths that switch us to a different strategy.
        return space.is_w(space.type(w_obj), space.w_unicode) and not self.jsonmap.is_state_blocked()

    def _never_equal_to(self, w_lookup_type):
        return False

    def length(self, w_dict):
        if self.jsonmap.is_state_blocked():
            self.switch_to_unicode_strategy(w_dict)
            return w_dict.length()
        return len(self.unerase(w_dict.dstorage))

    def getitem(self, w_dict, w_key):
        if self.is_correct_type(w_key):
            return self.getitem_unicode(w_dict, w_key)
        else:
            self.switch_to_unicode_strategy(w_dict)
            return w_dict.getitem(w_key)

    def getitem_unicode(self, w_dict, w_key):
        storage_w = self.unerase(w_dict.dstorage)
        if jit.isconstant(w_key):
            jit.promote(self)
        index = self.get_index(w_key)
        if index == -1:
            return None
        return storage_w[index]

    def setitem(self, w_dict, w_key, w_value):
        if self.is_correct_type(w_key):
            if jit.isconstant(w_key):
                jit.promote(self)
            storage_w = self.unerase(w_dict.dstorage)
            index = self.get_index(w_key)
            if index != -1:
                storage_w[index] = w_value
                return
        self.switch_to_unicode_strategy(w_dict)
        w_dict.setitem(w_key, w_value)

    def setdefault(self, w_dict, w_key, w_default):
        if self.is_correct_type(w_key):
            w_result = self.getitem_unicode(w_dict, w_key)
            if w_result is not None:
                return w_result
        self.switch_to_unicode_strategy(w_dict)
        return w_dict.setdefault(w_key, w_default)

    def delitem(self, w_dict, w_key):
        self.switch_to_unicode_strategy(w_dict)
        return w_dict.delitem(w_key)

    def popitem(self, w_dict):
        self.switch_to_unicode_strategy(w_dict)
        return w_dict.popitem()

    def switch_to_unicode_strategy(self, w_dict):
        strategy = self.space.fromcache(UnicodeDictStrategy)
        values_w = self.unerase(w_dict.dstorage)
        storage = strategy.get_empty_storage()
        d_new = strategy.unerase(storage)
        keys_in_order = self.get_keys_in_order()
        assert len(keys_in_order) == len(values_w)
        for index, w_key in enumerate(keys_in_order):
            assert w_key is not None
            assert type(w_key) is self.space.UnicodeObjectCls
            d_new[w_key] = values_w[index]
        w_dict.set_strategy(strategy)
        w_dict.dstorage = storage

    def w_keys(self, w_dict):
        return self.space.newlist(self.get_keys_in_order())

    def values(self, w_dict):
        return self.unerase(w_dict.dstorage)[:]  # to make resizable

    def items(self, w_dict):
        space = self.space
        storage_w = self.unerase(w_dict.dstorage)
        res = [None] * len(storage_w)
        for index, w_key in enumerate(self.get_keys_in_order()):
            res[index] = space.newtuple([w_key, storage_w[index]])
        return res

    def getiterkeys(self, w_dict):
        return iter(self.get_keys_in_order())

    def getitervalues(self, w_dict):
        storage_w = self.unerase(w_dict.dstorage)
        return iter(storage_w)

    def getiteritems_with_hash(self, w_dict):
        storage_w = self.unerase(w_dict.dstorage)
        return ZipItemsWithHash(self.get_keys_in_order(), storage_w)

    # ____________________________________________________________
    # methods for interpreting the jsonmaps

    @jit.elidable
    def get_index(self, w_key):
        from pypy.objspace.std.unicodeobject import W_UnicodeObject
        assert isinstance(w_key, W_UnicodeObject)
        return self.get_key_to_index().get(w_key, -1)

    def get_key_to_index(self):
        from pypy.objspace.std.dictmultiobject import unicode_hash, unicode_eq
        from pypy.module._pypyjson.interp_decoder import JSONMap
        key_to_index = self.key_to_index
        if key_to_index is None:
            key_to_index = self.key_to_index = objectmodel.r_dict(unicode_eq, unicode_hash,
                  force_non_null=True, simple_hash_eq=True)
            # compute depth
            curr = self.jsonmap
            depth = 0
            while True:
                depth += 1
                curr = curr.prev
                if not isinstance(curr, JSONMap):
                    break

            curr = self.jsonmap
            while depth:
                depth -= 1
                key_to_index[curr.w_key] = depth
                curr = curr.prev
                if not isinstance(curr, JSONMap):
                    break
        return key_to_index

    def get_keys_in_order(self):
        keys_in_order = self.keys_in_order
        if keys_in_order is None:
            key_to_index = self.get_key_to_index()
            keys_in_order = self.keys_in_order = [None] * len(key_to_index)
            for w_key, index in key_to_index.iteritems():
                keys_in_order[index] = w_key
        return keys_in_order


class ZipItemsWithHash(object):
    def __init__(self, list1, list2):
        assert len(list1) == len(list2)
        self.list1 = list1
        self.list2 = list2
        self.i = 0

    def __iter__(self):
        return self

    def next(self):
        i = self.i
        if i >= len(self.list1):
            raise StopIteration
        self.i = i + 1
        w_key = self.list1[i]
        return (w_key, self.list2[i], w_key.hash_w())


create_iterator_classes(JsonDictStrategy)
