import py
from pypy.lang.prolog.interpreter.interpreter import Rule, Frame
from pypy.lang.prolog.interpreter.parsing import get_engine, get_query_and_vars

def test_simple():
    e = get_engine("")
    head, body = get_query_and_vars("f(X) :- X = a.")[0].args
    r = Rule(head, body, e)
    query = get_query_and_vars("f(a).")[0]
    frame = r.make_frame(query)
    assert frame.localvarcache[0].dereference(e.heap).name == "a"
    cont = object()
    c2 = frame.run(frame.code.opcode, 0, cont)
    assert cont is c2

    query, vars = get_query_and_vars("f(X).")
    frame = r.make_frame(query)
    cont = object()
    c2 = frame.run(frame.code.opcode, 0, cont)
    assert cont is c2
    assert vars['X'].dereference(e.heap).name == 'a'

def test_build_term():
    e = get_engine("")
    head, body = get_query_and_vars("f(X, Y) :- X = a, Y = b.")[0].args
    r = Rule(head, body, e)

    frame = Frame(e, r.code)
    frame.run(frame.code.opcode_head, 0, None)
    frame.run(frame.code.opcode, 0, None)
    assert frame.stack[0].args[0].dereference(e.heap).name == "a"
    assert frame.stack[0].args[1].dereference(e.heap).name == "b"
