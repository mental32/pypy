import py
from pypy.jit.codewriter.codewriter import CodeWriter
from pypy.jit.codewriter import support
from pypy.jit.metainterp.history import AbstractDescr
from pypy.rpython.lltypesystem import lltype, llmemory

class FakeCallDescr(AbstractDescr):
    def __init__(self, FUNC, ARGS, RESULT, effectinfo=None):
        self.FUNC = FUNC
        self.ARGS = ARGS
        self.RESULT = RESULT
        self.effectinfo = effectinfo
    def get_extra_info(self):
        return self.effectinfo

class FakeFieldDescr(AbstractDescr):
    def __init__(self, STRUCT, fieldname):
        self.STRUCT = STRUCT
        self.fieldname = fieldname

class FakeSizeDescr(AbstractDescr):
    def __init__(self, STRUCT):
        self.STRUCT = STRUCT

class FakeCPU:
    def __init__(self, rtyper):
        self.rtyper = rtyper
    calldescrof = FakeCallDescr
    fielddescrof = FakeFieldDescr
    sizeof = FakeSizeDescr

class FakePolicy:
    def look_inside_graph(self, graph):
        return True


def test_loop():
    def f(a, b):
        while a > 0:
            b += a
            a -= 1
        return b
    cw = CodeWriter()
    jitcode = cw.transform_func_to_jitcode(f, [5, 6])
    assert jitcode.code == ("\x00\x00\x00\x10\x00"   # ends at 5
                            "\x01\x01\x00\x01"
                            "\x02\x00\x01\x00"
                            "\x03\x00\x00"
                            "\x04\x01")
    assert cw.assembler.insns == {'goto_if_not_int_gt/icL': 0,
                                  'int_add/ii>i': 1,
                                  'int_sub/ic>i': 2,
                                  'goto/L': 3,
                                  'int_return/i': 4}
    assert jitcode.num_regs_i() == 2
    assert jitcode.num_regs_r() == 0
    assert jitcode.num_regs_f() == 0
    assert jitcode._live_vars(5) == '%i0 %i1'
    #
    from pypy.jit.codewriter.jitcode import MissingLiveness
    for i in range(len(jitcode.code)+1):
        if i != 5:
            py.test.raises(MissingLiveness, jitcode._live_vars, i)

def test_call():
    def ggg(x):
        return x * 2
    def fff(a, b):
        return ggg(b) - ggg(a)
    rtyper = support.annotate(fff, [35, 42])
    maingraph = rtyper.annotator.translator.graphs[0]
    cw = CodeWriter(FakeCPU(rtyper), maingraph)
    cw.find_all_graphs(FakePolicy())
    cw.make_jitcodes(verbose=True)
    jitcode = cw.mainjitcode
    print jitcode.dump()
    [jitcode2] = cw.assembler.descrs
    print jitcode2.dump()
    assert jitcode is not jitcode2
    assert jitcode.name == 'fff'
    assert jitcode2.name == 'ggg'
    assert 'ggg' in jitcode.dump()
    assert lltype.typeOf(jitcode2.fnaddr) == llmemory.Address
    assert isinstance(jitcode2.calldescr, FakeCallDescr)

def test_integration():
    from pypy.jit.metainterp.blackhole import BlackholeInterpBuilder
    def f(a, b):
        while a > 2:
            b += a
            a -= 1
        return b
    cw = CodeWriter()
    jitcode = cw.transform_func_to_jitcode(f, [5, 6])
    blackholeinterpbuilder = BlackholeInterpBuilder(cw)
    blackholeinterp = blackholeinterpbuilder.acquire_interp()
    blackholeinterp.setposition(jitcode, 0)
    blackholeinterp.setarg_i(0, 6)
    blackholeinterp.setarg_i(1, 100)
    blackholeinterp.run()
    assert blackholeinterp.final_result_i() == 100+6+5+4+3

def test_instantiate():
    class A1:     id = 651
    class A2(A1): id = 652
    class B1:     id = 661
    class B2(B1): id = 662
    def f(n):
        if n > 5:
            x, y = A1, B1
        else:
            x, y = A2, B2
        n += 1
        return x().id + y().id + n
    rtyper = support.annotate(f, [35])
    maingraph = rtyper.annotator.translator.graphs[0]
    cw = CodeWriter(FakeCPU(rtyper), maingraph)
    cw.find_all_graphs(FakePolicy())
    cw.make_jitcodes(verbose=True)
    #
    assert len(cw.assembler.indirectcalltargets) == 4
    names = [jitcode.name for jitcode in cw.assembler.indirectcalltargets]
    for expected in ['A1', 'A2', 'B1', 'B2']:
        for name in names:
            if name.startswith('instantiate_') and name.endswith(expected):
                break
        else:
            assert 0, "missing instantiate_*_%s in:\n%r" % (expected,
                                                            names)

def test_int_abs():
    def f(n):
        return abs(n)
    rtyper = support.annotate(f, [35])
    maingraph = rtyper.annotator.translator.graphs[0]
    cw = CodeWriter(FakeCPU(rtyper), maingraph)
    cw.find_all_graphs(FakePolicy())
    cw.make_jitcodes(verbose=True)
    #
    s = cw.mainjitcode.dump()
    assert "inline_call_ir_i <JitCode '_ll_1_int_abs__Signed'>" in s
