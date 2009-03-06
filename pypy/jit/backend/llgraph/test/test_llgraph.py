import py
from pypy.rpython.lltypesystem import lltype, llmemory, rstr, rclass
from pypy.rpython.test.test_llinterp import interpret
from pypy.rlib.unroll import unrolling_iterable

from pypy.jit.metainterp.history import BoxInt, BoxPtr, Const, ConstInt
from pypy.jit.metainterp.resoperation import ResOperation, rop
from pypy.jit.metainterp.executor import get_execute_function
from pypy.jit.backend.llgraph.runner import CPU, GuardFailed


class FakeMetaInterp(object):
    def __init__(self, cpu):
        self.cpu = cpu
    def handle_guard_failure(self, gf):
        assert isinstance(gf, GuardFailed)
        self.gf = gf
        self.recordedvalues = [
                self.cpu.getvaluebox(gf.frame, gf.guard_op, i).value
                    for i in range(len(gf.guard_op.liveboxes))]
        gf.make_ready_for_return(BoxInt(42))

NODE = lltype.GcForwardReference()
NODE.become(lltype.GcStruct('NODE', ('value', lltype.Signed),
                                    ('next', lltype.Ptr(NODE))))

SUBNODE = lltype.GcStruct('SUBNODE', ('parent', NODE))


class TestLLGraph:

    def eval_llinterp(self, runme, *args, **kwds):
        expected_class = kwds.pop('expected_class', None)
        expected_vals = [(name[9:], kwds[name])
                            for name in kwds.keys()
                                if name.startswith('expected_')]
        expected_vals = unrolling_iterable(expected_vals)

        def main():
            res = runme(*args)
            if expected_class is not None:
                assert isinstance(res, expected_class)
                for key, value in expected_vals:
                    assert getattr(res, key) == value
        interpret(main, [])

    def test_simple(self):
        cpu = CPU(None)
        box = cpu.execute_operation(rop.INT_SUB, [BoxInt(10), BoxInt(2)],
                                    "int")
        assert isinstance(box, BoxInt)
        assert box.value == 8

    def test_execute_operation(self):
        cpu = CPU(None)
        node = lltype.malloc(NODE)
        node_value = cpu.fielddescrof(NODE, 'value')
        nodeadr = lltype.cast_opaque_ptr(llmemory.GCREF, node)
        box = cpu.execute_operation(rop.SETFIELD_GC, [BoxPtr(nodeadr),
                                                      ConstInt(node_value),
                                                      BoxInt(3)],
                                    'void')
        assert box is None
        assert node.value == 3

        box = cpu.execute_operation(rop.GETFIELD_GC, [BoxPtr(nodeadr),
                                                      ConstInt(node_value)],
                                    'int')
        assert box.value == 3

    def test_execute_operations_in_env(self):
        cpu = CPU(None)
        cpu.set_meta_interp(FakeMetaInterp(cpu))
        x = BoxInt(123)
        y = BoxInt(456)
        z = BoxInt(579)
        t = BoxInt(455)
        u = BoxInt(0)
        operations = [
            ResOperation(rop.MERGE_POINT, [x, y], None),
            ResOperation(rop.INT_ADD, [x, y], z),
            ResOperation(rop.INT_SUB, [y, ConstInt(1)], t),
            ResOperation(rop.INT_EQ, [t, ConstInt(0)], u),
            ResOperation(rop.GUARD_FALSE, [u], None),
            ResOperation(rop.JUMP, [z, t], None),
            ]
        operations[-2].liveboxes = [t, z]
        startmp = operations[0]
        operations[-1].jump_target = startmp
        cpu.compile_operations(operations)
        res = cpu.execute_operations_in_new_frame('foo', startmp,
                                                  [BoxInt(0), BoxInt(10)])
        assert res.value == 42
        gf = cpu.metainterp.gf
        assert cpu.metainterp.recordedvalues == [0, 55]
        assert gf.guard_op is operations[-2]
        assert cpu.stats.exec_counters['int_add'] == 10
        assert cpu.stats.exec_jumps == 9

    def test_passing_guards(self):
        py.test.skip("rewrite me")
        cpu = CPU(None)
        assert cpu.execute_operation(rop.GUARD_TRUE, [BoxInt(1)],
                                     'void') == None
        assert cpu.execute_operation(rop.GUARD_FALSE,[BoxInt(0)],
                                     'void') == None
        assert cpu.execute_operation(rop.GUARD_VALUE,[BoxInt(42), BoxInt(42)],
                                     'void') == None
        #subnode = lltype.malloc(SUBNODE)
        #assert cpu.execute_operation('guard_class', [subnode, SUBNODE]) == []
        #assert cpu.stats.exec_counters == {'guard_true': 1, 'guard_false': 1,
        #                                   'guard_value': 1, 'guard_class': 1}
        #assert cpu.stats.exec_jumps == 0

    def test_failing_guards(self):
        py.test.skip("rewrite me")
        cpu = CPU(None)
        cpu.set_meta_interp(FakeMetaInterp(cpu))
        #node = ootype.new(NODE)
        #subnode = ootype.new(SUBNODE)
        for opnum, args in [(rop.GUARD_TRUE, [BoxInt(0)]),
                            (rop.GUARD_FALSE, [BoxInt(1)]),
                            (rop.GUARD_VALUE, [BoxInt(42), BoxInt(41)]),
                            #('guard_class', [node, SUBNODE]),
                            #('guard_class', [subnode, NODE]),
                            ]:
            operations = [
                ResOperation(rop.MERGE_POINT, args, []),
                ResOperation(opnum, args, []),
                ResOperation(rop.VOID_RETURN, [], []),
                ]
            startmp = operations[0]
            cpu.compile_operations(operations)
            res = cpu.execute_operations_in_new_frame('foo', startmp, args)
            assert res.value == 42

    def test_cast_adr_to_int_and_back(self):
        cpu = CPU(None)
        X = lltype.Struct('X', ('foo', lltype.Signed))
        x = lltype.malloc(X, immortal=True)
        x.foo = 42
        a = llmemory.cast_ptr_to_adr(x)
        i = cpu.cast_adr_to_int(a)
        assert isinstance(i, int)
        a2 = cpu.cast_int_to_adr(i)
        assert llmemory.cast_adr_to_ptr(a2, lltype.Ptr(X)) == x
        assert cpu.cast_adr_to_int(llmemory.NULL) == 0
        assert cpu.cast_int_to_adr(0) == llmemory.NULL

    def test_llinterp_simple(self):
        py.test.skip("rewrite me")
        cpu = CPU(None)
        self.eval_llinterp(cpu.execute_operation, "int_sub",
                           [BoxInt(10), BoxInt(2)], "int",
                           expected_class = BoxInt,
                           expected_value = 8)

    def test_do_operations(self):
        cpu = CPU(None)
        #
        A = lltype.GcArray(lltype.Char)
        descrbox_A = ConstInt(cpu.arraydescrof(A))
        a = lltype.malloc(A, 5)
        x = cpu.do_arraylen_gc(
            [BoxPtr(lltype.cast_opaque_ptr(llmemory.GCREF, a)), descrbox_A])
        assert x.value == 5
        #
        a[2] = 'Y'
        x = cpu.do_getarrayitem_gc(
            [BoxPtr(lltype.cast_opaque_ptr(llmemory.GCREF, a)), descrbox_A,
             BoxInt(2)])
        assert x.value == ord('Y')
        #
        B = lltype.GcArray(lltype.Ptr(A))
        descrbox_B = ConstInt(cpu.arraydescrof(B))
        b = lltype.malloc(B, 4)
        b[3] = a
        x = cpu.do_getarrayitem_gc(
            [BoxPtr(lltype.cast_opaque_ptr(llmemory.GCREF, b)), descrbox_B,
             BoxInt(3)])
        assert isinstance(x, BoxPtr)
        assert x.getptr(lltype.Ptr(A)) == a
        #
        s = rstr.mallocstr(6)
        x = cpu.do_strlen(
            [BoxPtr(lltype.cast_opaque_ptr(llmemory.GCREF, s))])
        assert x.value == 6
        #
        s.chars[3] = 'X'
        x = cpu.do_strgetitem(
            [BoxPtr(lltype.cast_opaque_ptr(llmemory.GCREF, s)), BoxInt(3)])
        assert x.value == ord('X')
        #
        S = lltype.GcStruct('S', ('x', lltype.Char), ('y', lltype.Ptr(A)))
        descrfld_x = cpu.fielddescrof(S, 'x')
        s = lltype.malloc(S)
        s.x = 'Z'
        x = cpu.do_getfield_gc(
            [BoxPtr(lltype.cast_opaque_ptr(llmemory.GCREF, s)),
             BoxInt(descrfld_x)])
        assert x.value == ord('Z')
        #
        cpu.do_setfield_gc(
            [BoxPtr(lltype.cast_opaque_ptr(llmemory.GCREF, s)),
             BoxInt(descrfld_x),
             BoxInt(ord('4'))])
        assert s.x == '4'
        #
        descrfld_y = cpu.fielddescrof(S, 'y')
        s.y = a
        x = cpu.do_getfield_gc(
            [BoxPtr(lltype.cast_opaque_ptr(llmemory.GCREF, s)),
             BoxInt(descrfld_y)])
        assert isinstance(x, BoxPtr)
        assert x.getptr(lltype.Ptr(A)) == a
        #
        s.y = lltype.nullptr(A)
        cpu.do_setfield_gc(
            [BoxPtr(lltype.cast_opaque_ptr(llmemory.GCREF, s)),
             BoxInt(descrfld_y),
             x])
        assert s.y == a
        #
        RS = lltype.Struct('S', ('x', lltype.Char), ('y', lltype.Ptr(A)))
        descrfld_rx = cpu.fielddescrof(RS, 'x')
        rs = lltype.malloc(RS, immortal=True)
        rs.x = '?'
        x = cpu.do_getfield_raw(
            [BoxInt(cpu.cast_adr_to_int(llmemory.cast_ptr_to_adr(rs))),
             BoxInt(descrfld_rx)])
        assert x.value == ord('?')
        #
        cpu.do_setfield_raw(
            [BoxInt(cpu.cast_adr_to_int(llmemory.cast_ptr_to_adr(rs))),
             BoxInt(descrfld_rx),
             BoxInt(ord('!'))])
        assert rs.x == '!'
        #
        descrfld_ry = cpu.fielddescrof(RS, 'y')
        rs.y = a
        x = cpu.do_getfield_raw(
            [BoxInt(cpu.cast_adr_to_int(llmemory.cast_ptr_to_adr(rs))),
             BoxInt(descrfld_ry)])
        assert isinstance(x, BoxPtr)
        assert x.getptr(lltype.Ptr(A)) == a
        #
        rs.y = lltype.nullptr(A)
        cpu.do_setfield_raw(
            [BoxInt(cpu.cast_adr_to_int(llmemory.cast_ptr_to_adr(rs))),
             BoxInt(descrfld_ry),
             x])
        assert rs.y == a
        #
        descrsize = cpu.sizeof(S)
        x = cpu.do_new(
            [BoxInt(descrsize)])
        assert isinstance(x, BoxPtr)
        x.getptr(lltype.Ptr(S))
        #
        descrsize2 = cpu.sizeof(rclass.OBJECT)
        vtable2 = lltype.malloc(rclass.OBJECT_VTABLE, immortal=True)
        x = cpu.do_new_with_vtable(
            [BoxInt(descrsize2),
             BoxInt(cpu.cast_adr_to_int(llmemory.cast_ptr_to_adr(vtable2)))])
        assert isinstance(x, BoxPtr)
        assert x.getptr(rclass.OBJECTPTR).typeptr == vtable2
        #
        arraydescr = cpu.arraydescrof(A)
        x = cpu.do_new_array(
            [BoxInt(arraydescr), BoxInt(7)])
        assert isinstance(x, BoxPtr)
        assert len(x.getptr(lltype.Ptr(A))) == 7
        #
        cpu.do_setarrayitem_gc(
            [x, descrbox_A, BoxInt(5), BoxInt(ord('*'))])
        assert x.getptr(lltype.Ptr(A))[5] == '*'
        #
        cpu.do_setarrayitem_gc(
            [BoxPtr(lltype.cast_opaque_ptr(llmemory.GCREF, b)), descrbox_B,
             BoxInt(1), x])
        assert b[1] == x.getptr(lltype.Ptr(A))
        #
        x = cpu.do_newstr([BoxInt(5)])
        assert isinstance(x, BoxPtr)
        assert len(x.getptr(lltype.Ptr(rstr.STR)).chars) == 5
        #
        cpu.do_strsetitem([x, BoxInt(4), BoxInt(ord('/'))])
        assert x.getptr(lltype.Ptr(rstr.STR)).chars[4] == '/'

    def test_do_call(self):
        from pypy.rpython.annlowlevel import llhelper
        cpu = CPU(None)
        #
        def func(c):
            return chr(ord(c) + 1)
        FPTR = lltype.Ptr(lltype.FuncType([lltype.Char], lltype.Char))
        func_ptr = llhelper(FPTR, func)
        calldescr = cpu.calldescrof([lltype.Char], lltype.Char)
        x = cpu.do_call(
            [BoxInt(cpu.cast_adr_to_int(llmemory.cast_ptr_to_adr(func_ptr))),
             ConstInt(calldescr),
             BoxInt(ord('A'))])
        assert x.value == ord('B')

    def test_executor(self):
        cpu = CPU(None)
        fn = get_execute_function(cpu, rop.INT_ADD)
        assert fn(cpu, [BoxInt(100), ConstInt(42)]).value == 142
        fn = get_execute_function(cpu, rop.NEWSTR)
        s = fn(cpu, [BoxInt(8)])
        assert len(s.getptr(lltype.Ptr(rstr.STR)).chars) == 8
