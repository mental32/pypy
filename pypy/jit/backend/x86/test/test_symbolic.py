import py
py.test.skip("update me")
from pypy.jit.backend.x86.symbolic import *
from pypy.jit.backend.x86.runner import CPU386
from pypy.rpython.lltypesystem import lltype, rffi

class FakeStats(object):
    pass

S = lltype.GcStruct('S', ('x', lltype.Signed),
                         ('y', lltype.Signed),
                         ('z', lltype.Signed))


def test_field_token():
    ofs_x, size_x = get_field_token(S, 'x')
    ofs_y, size_y = get_field_token(S, 'y')
    ofs_z, size_z = get_field_token(S, 'z')
    # ofs_x might be 0 or not, depending on how we count the headers
    # but the rest should be as expected for a 386 machine
    assert size_x == size_y == size_z == 4
    assert ofs_x >= 0
    assert ofs_y == ofs_x + 4
    assert ofs_z == ofs_x + 8

def test_struct_size():
    ofs_z, size_z = get_field_token(S, 'z')
    totalsize = get_size(S)
    assert totalsize == ofs_z + 4

def test_primitive_size():
    assert get_size(lltype.Signed) == 4
    assert get_size(lltype.Char) == 1
    assert get_size(lltype.Ptr(S)) == 4

def test_array_token():
    A = lltype.GcArray(lltype.Char)
    basesize, itemsize, ofs_length = get_array_token(A)
    assert basesize >= 4    # at least the 'length', maybe some gc headers
    assert itemsize == 1
    assert ofs_length == basesize - 4
    A = lltype.GcArray(lltype.Signed)
    basesize, itemsize, ofs_length = get_array_token(A)
    assert basesize >= 4    # at least the 'length', maybe some gc headers
    assert itemsize == 4
    assert ofs_length == basesize - 4

def test_varsized_struct_size():
    S1 = lltype.GcStruct('S1', ('parent', S),
                               ('extra', lltype.Signed),
                               ('chars', lltype.Array(lltype.Char)))
    size_parent = get_size(S)
    ofs_extra, size_extra = get_field_token(S1, 'extra')
    basesize, itemsize, ofs_length = get_array_token(S1)
    assert size_parent == ofs_extra
    assert size_extra == 4
    assert ofs_length == ofs_extra + 4
    assert basesize == ofs_length + 4
    assert itemsize == 1

def test_methods_of_cpu():
    cpu = CPU386(rtyper=None, stats=FakeStats())
    assert cpu.sizeof(S) == get_size(S)
    assert cpu.fielddescrof(S, 'y') & 0xffff == get_field_token(S, 'y')[0]
    assert cpu.fielddescrof(S, 'y') >> 16 == get_field_token(S, 'y')[1]
    A = lltype.GcArray(lltype.Char)
    #assert cpu.itemoffsetof(A) == get_array_token(A)[0]
    #assert cpu.arraylengthoffset(A) == get_array_token(A)[2]

def test_string():
    STR = lltype.GcStruct('String', ('hash', lltype.Signed),
                                    ('chars', lltype.Array(lltype.Char)))
    basesize, itemsize, ofs_length = get_array_token(STR)
    assert itemsize == 1
    s1 = lltype.malloc(STR, 4)
    s1.chars[0] = 's'
    s1.chars[1] = 'p'
    s1.chars[2] = 'a'
    s1.chars[3] = 'm'
    x = ll2ctypes.lltype2ctypes(s1)
    rawbytes = ctypes.cast(x, ctypes.POINTER(ctypes.c_char))
    assert rawbytes[basesize+0] == 's'
    assert rawbytes[basesize+1] == 'p'
    assert rawbytes[basesize+2] == 'a'
    assert rawbytes[basesize+3] == 'm'
    assert rawbytes[ofs_length+0] == chr(4)
    assert rawbytes[ofs_length+1] == chr(0)
    assert rawbytes[ofs_length+2] == chr(0)
    assert rawbytes[ofs_length+3] == chr(0)
