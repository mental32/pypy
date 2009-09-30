
from pypy.rpython.ootypesystem import ootype
from pypy.objspace.flow.model import Constant, Variable
from pypy.rlib.objectmodel import we_are_translated
from pypy.conftest import option

from pypy.jit.metainterp.resoperation import ResOperation, rop
from pypy.jit.metainterp.history import TreeLoop, log, Box, History, LoopToken
from pypy.jit.metainterp.history import AbstractFailDescr, BoxInt
from pypy.jit.metainterp.history import BoxPtr, BoxObj, BoxFloat, Const
from pypy.jit.metainterp import history
from pypy.jit.metainterp.specnode import NotSpecNode, more_general_specnodes
from pypy.jit.metainterp.typesystem import llhelper, oohelper
from pypy.jit.metainterp.optimizeutil import InvalidLoop
from pypy.rlib.debug import debug_print

def show_loop(metainterp_sd, loop=None, error=None):
    # debugging
    if option.view or option.viewloops:
        if error:
            errmsg = error.__class__.__name__
            if str(error):
                errmsg += ': ' + str(error)
        else:
            errmsg = None
        if loop is None: # or type(loop) is TerminatingLoop:
            extraloops = []
        else:
            extraloops = [loop]
        metainterp_sd.stats.view(errmsg=errmsg, extraloops=extraloops)

def create_empty_loop(metainterp):
    name = metainterp.staticdata.stats.name_for_new_loop()
    return TreeLoop(name)

# ____________________________________________________________

def compile_new_loop(metainterp, old_loop_tokens, greenkey, start):
    """Try to compile a new loop by closing the current history back
    to the first operation.
    """    
    history = metainterp.history
    loop = create_empty_loop(metainterp)
    loop.greenkey = greenkey
    loop.inputargs = history.inputargs
    for box in loop.inputargs:
        assert isinstance(box, Box)
    if start > 0:
        loop.operations = history.operations[start:]
    else:
        loop.operations = history.operations
    loop.operations[-1].jump_target = None
    metainterp_sd = metainterp.staticdata
    try:
        old_loop_token = metainterp_sd.state.optimize_loop(
            metainterp_sd.options, old_loop_tokens, loop, metainterp.cpu)
    except InvalidLoop:
        return None
    if old_loop_token is not None:
        if metainterp.staticdata.state.debug > 0:
            debug_print("reusing old loop")
        return old_loop_token
    executable_token = send_loop_to_backend(metainterp_sd, loop, "loop")
    loop_token = LoopToken()
    loop_token.specnodes = loop.specnodes
    loop_token.executable_token = executable_token
    if not we_are_translated():
        loop.token = loop_token
    insert_loop_token(old_loop_tokens, loop_token)
    return loop_token

def insert_loop_token(old_loop_tokens, loop_token):
    # Find where in old_loop_tokens we should insert this new loop_token.
    # The following algo means "as late as possible, but before another
    # loop token that would be more general and so completely mask off
    # the new loop_token".
    for i in range(len(old_loop_tokens)):
        if more_general_specnodes(old_loop_tokens[i].specnodes,
                                  loop_token.specnodes):
            old_loop_tokens.insert(i, loop_token)
            break
    else:
        old_loop_tokens.append(loop_token)

def send_loop_to_backend(metainterp_sd, loop, type):
    metainterp_sd.options.logger_ops.log_loop(loop.inputargs, loop.operations)
    metainterp_sd.state.profiler.start_backend()
    if not we_are_translated():
        show_loop(metainterp_sd, loop)
        loop.check_consistency()
    executable_token = metainterp_sd.cpu.compile_loop(loop.inputargs,
                                                      loop.operations)
    metainterp_sd.state.profiler.end_backend()
    metainterp_sd.stats.add_new_loop(loop)
    if not we_are_translated():
        if type != "entry bridge":
            metainterp_sd.stats.compiled()
        else:
            loop._ignore_during_counting = True
        if metainterp_sd.state.debug > 0:
            log.info("compiled new " + type)
    else:
        if metainterp_sd.state.debug > 0:
            debug_print("compiled new " + type)
    return executable_token

def send_bridge_to_backend(metainterp_sd, faildescr, inputargs, operations):
    metainterp_sd.options.logger_ops.log_loop(inputargs, operations)
    metainterp_sd.state.profiler.start_backend()
    if not we_are_translated():
        show_loop(metainterp_sd)
        TreeLoop.check_consistency_of(inputargs, operations)
        pass
    metainterp_sd.cpu.compile_bridge(faildescr, inputargs, operations)        
    metainterp_sd.state.profiler.end_backend()
    if not we_are_translated():
        if metainterp_sd.state.debug > 0:
            metainterp_sd.stats.compiled()
            log.info("compiled new bridge")
    else:
        if metainterp_sd.state.debug > 0:
            debug_print("compiled new bridge")            

# ____________________________________________________________

class DoneWithThisFrameDescrVoid(AbstractFailDescr):
    def handle_fail(self, metainterp_sd):
        assert metainterp_sd.result_type == 'void'
        raise metainterp_sd.DoneWithThisFrameVoid()

class DoneWithThisFrameDescrInt(AbstractFailDescr):
    def handle_fail(self, metainterp_sd):
        assert metainterp_sd.result_type == 'int'
        result = metainterp_sd.cpu.get_latest_value_int(0)
        raise metainterp_sd.DoneWithThisFrameInt(result)

class DoneWithThisFrameDescrRef(AbstractFailDescr):
    def handle_fail(self, metainterp_sd):
        assert metainterp_sd.result_type == 'ref'
        cpu = metainterp_sd.cpu
        result = cpu.get_latest_value_ref(0)
        raise metainterp_sd.DoneWithThisFrameRef(cpu, result)

class DoneWithThisFrameDescrFloat(AbstractFailDescr):
    def handle_fail(self, metainterp_sd):
        assert metainterp_sd.result_type == 'float'
        result = metainterp_sd.cpu.get_latest_value_float(0)
        raise metainterp_sd.DoneWithThisFrameFloat(result)

class ExitFrameWithExceptionDescrRef(AbstractFailDescr):
    def handle_fail(self, metainterp_sd):
        cpu = metainterp_sd.cpu
        value = cpu.get_latest_value_ref(0)
        raise metainterp_sd.ExitFrameWithExceptionRef(cpu, value)

done_with_this_frame_descr_void = DoneWithThisFrameDescrVoid()
done_with_this_frame_descr_int = DoneWithThisFrameDescrInt()
done_with_this_frame_descr_ref = DoneWithThisFrameDescrRef()
done_with_this_frame_descr_float = DoneWithThisFrameDescrFloat()
exit_frame_with_exception_descr_ref = ExitFrameWithExceptionDescrRef()


prebuiltNotSpecNode = NotSpecNode()

class TerminatingLoopToken(LoopToken):
    terminating = True
    
    def __init__(self, nargs, finishdescr):
        self.specnodes = [prebuiltNotSpecNode]*nargs
        self.finishdescr = finishdescr

# pseudo loop tokens to make the life of optimize.py easier
loop_tokens_done_with_this_frame_int = [
    TerminatingLoopToken(1, done_with_this_frame_descr_int)
    ]
loop_tokens_done_with_this_frame_ref = [
    TerminatingLoopToken(1, done_with_this_frame_descr_ref)
    ]
loop_tokens_done_with_this_frame_float = [
    TerminatingLoopToken(1, done_with_this_frame_descr_float)
    ]
loop_tokens_done_with_this_frame_void = [
    TerminatingLoopToken(0, done_with_this_frame_descr_void)
    ]
loop_tokens_exit_frame_with_exception_ref = [
    TerminatingLoopToken(1, exit_frame_with_exception_descr_ref)
    ]

class ResumeDescr(AbstractFailDescr):
    def __init__(self, original_greenkey):
        self.original_greenkey = original_greenkey

class ResumeGuardDescr(ResumeDescr):
    counter = 0
    # this class also gets attributes stored by resume.py code

    def store_final_boxes(self, guard_op, boxes):
        guard_op.fail_args = boxes
        self.guard_opnum = guard_op.opnum
        self.fail_arg_types = [box.type for box in boxes]

    def handle_fail(self, metainterp_sd):
        from pypy.jit.metainterp.pyjitpl import MetaInterp
        metainterp = MetaInterp(metainterp_sd)
        return metainterp.handle_guard_failure(self)

    def compile_and_attach(self, metainterp, new_loop):
        # We managed to create a bridge.  Attach the new operations
        # to the corrsponding guard_op and compile from there
        inputargs = metainterp.history.inputargs
        if not we_are_translated():
            self._debug_suboperations = new_loop.operations
        send_bridge_to_backend(metainterp.staticdata, self, inputargs,
                               new_loop.operations)

class ResumeFromInterpDescr(ResumeDescr):
    def __init__(self, original_greenkey, redkey):
        ResumeDescr.__init__(self, original_greenkey)
        self.redkey = redkey

    def compile_and_attach(self, metainterp, new_loop):
        # We managed to create a bridge going from the interpreter
        # to previously-compiled code.  We keep 'new_loop', which is not
        # a loop at all but ends in a jump to the target loop.  It starts
        # with completely unoptimized arguments, as in the interpreter.
        metainterp_sd = metainterp.staticdata
        metainterp.history.inputargs = self.redkey
        new_loop.greenkey = self.original_greenkey
        new_loop.inputargs = self.redkey
        executable_token = send_loop_to_backend(metainterp_sd, new_loop,
                                                "entry bridge")
        # send the new_loop to warmspot.py, to be called directly the next time
        metainterp_sd.state.attach_unoptimized_bridge_from_interp(
            self.original_greenkey,
            executable_token)
        # store the new loop in compiled_merge_points too
        glob = metainterp_sd.globaldata
        greenargs = glob.unpack_greenkey(self.original_greenkey)
        old_loop_tokens = glob.compiled_merge_points.setdefault(greenargs, [])
        new_loop_token = LoopToken()
        new_loop_token.specnodes = [prebuiltNotSpecNode] * len(self.redkey)
        new_loop_token.executable_token = executable_token
        # it always goes at the end of the list, as it is the most
        # general loop token
        old_loop_tokens.append(new_loop_token)


def compile_new_bridge(metainterp, old_loop_tokens, resumekey):
    """Try to compile a new bridge leading from the beginning of the history
    to some existing place.
    """    
    # The history contains new operations to attach as the code for the
    # failure of 'resumekey.guard_op'.
    #
    # Attempt to use optimize_bridge().  This may return None in case
    # it does not work -- i.e. none of the existing old_loop_tokens match.
    new_loop = create_empty_loop(metainterp)
    new_loop.inputargs = metainterp.history.inputargs
    new_loop.operations = metainterp.history.operations
    metainterp_sd = metainterp.staticdata
    options = metainterp_sd.options
    try:
        target_loop_token = metainterp_sd.state.optimize_bridge(options,
                                                          old_loop_tokens,
                                                          new_loop,
                                                          metainterp.cpu)
    except InvalidLoop:
        assert 0, "InvalidLoop in optimize_bridge?"
        return None
    # Did it work?
    if target_loop_token is not None:
        # Yes, we managed to create a bridge.  Dispatch to resumekey to
        # know exactly what we must do (ResumeGuardDescr/ResumeFromInterpDescr)
        prepare_last_operation(new_loop, target_loop_token)
        resumekey.compile_and_attach(metainterp, new_loop)
    return target_loop_token

def prepare_last_operation(new_loop, target_loop_token):
    op = new_loop.operations[-1]
    if not isinstance(target_loop_token, TerminatingLoopToken):
        # normal case
        op.jump_target = target_loop_token
    else:
        # The target_loop_token is a pseudo loop token,
        # e.g. loop_tokens_done_with_this_frame_void[0]
        # Replace the operation with the real operation we want, i.e. a FAIL.
        descr = target_loop_token.finishdescr
        new_op = ResOperation(rop.FINISH, op.args, None, descr=descr)
        new_loop.operations[-1] = new_op
