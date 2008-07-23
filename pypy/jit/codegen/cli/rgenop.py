from pypy.tool.pairtype import extendabletype
from pypy.rlib.rarithmetic import intmask
from pypy.rpython.ootypesystem import ootype
from pypy.rpython.lltypesystem import lltype
from pypy.rlib.objectmodel import specialize
from pypy.jit.codegen.model import AbstractRGenOp, GenBuilder, GenLabel
from pypy.jit.codegen.model import GenVarOrConst, GenVar, GenConst
from pypy.jit.codegen.model import CodeGenSwitch
from pypy.jit.codegen.cli import operation as ops
from pypy.jit.codegen.cli.methodfactory import get_method_wrapper
from pypy.translator.cli.dotnet import CLR, typeof, new_array, init_array
from pypy.translator.cli.dotnet import box, unbox, clidowncast, classof
from pypy.translator.cli import dotnet
System = CLR.System
DelegateHolder = CLR.pypy.runtime.DelegateHolder
LowLevelFlexSwitch = CLR.pypy.runtime.LowLevelFlexSwitch
InputArgs = CLR.pypy.runtime.InputArgs
OpCodes = System.Reflection.Emit.OpCodes

cVoid = ootype.nullruntimeclass
cInt32 = classof(System.Int32)
cBoolean = classof(System.Boolean)
cDouble = classof(System.Double)
cObject = classof(System.Object)
cString = classof(System.String)
cChar = classof(System.Char)
cInputArgs = classof(InputArgs)
cUtils = classof(CLR.pypy.runtime.Utils)

class SigToken:
    def __init__(self, args, res, funcclass):
        self.args = args
        self.res = res
        self.funcclass = funcclass

def class2type(cls):
    'Cast a PBC of type ootype.Class into a System.Type instance'
    if cls is cVoid:
        return None
    else:
        return clidowncast(box(cls), System.Type)

class __extend__(GenVarOrConst):
    __metaclass__ = extendabletype

    def getCliType(self):
        raise NotImplementedError
    
    def load(self, builder):
        raise NotImplementedError

    def store(self, builder):
        raise NotImplementedError

class GenArgVar(GenVar):
    def __init__(self, index, cliType):
        self.index = index
        self.cliType = cliType

    def getCliType(self):
        return self.cliType

    def load(self, meth):
        if self.index == 0:
            meth.il.Emit(OpCodes.Ldarg_0)
        elif self.index == 1:
            meth.il.Emit(OpCodes.Ldarg_1)
        elif self.index == 2:
            meth.il.Emit(OpCodes.Ldarg_2)
        elif self.index == 3:
            meth.il.Emit(OpCodes.Ldarg_3)
        else:
            meth.il.Emit(OpCodes.Ldarg, self.index)

    def store(self, meth):
        meth.il.Emit(OpCodes.Starg, self.index)

    def __repr__(self):
        return "GenArgVar(%d)" % self.index

class GenLocalVar(GenVar):
    def __init__(self, v):
        self.v = v

    def getCliType(self):
        return self.v.get_LocalType()

    def load(self, meth):
        meth.il.Emit(OpCodes.Ldloc, self.v)

    def store(self, meth):
        meth.il.Emit(OpCodes.Stloc, self.v)


class IntConst(GenConst):

    def __init__(self, value, cliclass):
        self.value = value
        self.cliclass = cliclass

    @specialize.arg(1)
    def revealconst(self, T):
        if T is ootype.Object:
            return ootype.NULL # XXX?
        elif isinstance(T, ootype.OOType):
            return ootype.null(T) # XXX
        return lltype.cast_primitive(T, self.value)

    def getCliType(self):
        return class2type(self.cliclass)

    def load(self, meth):
        meth.il.Emit(OpCodes.Ldc_I4, self.value)

    def __repr__(self):
        return "int const=%s" % self.value


class FloatConst(GenConst):

    def __init__(self, value):
        self.value = value

    @specialize.arg(1)
    def revealconst(self, T):
        if T is ootype.Object:
            return ootype.NULL # XXX?
        return lltype.cast_primitive(T, self.value)

    def getCliType(self):
        return typeof(System.Double)

    def load(self, meth):
        meth.il.Emit(OpCodes.Ldc_R8, self.value)

    def __repr__(self):
        return "float const=%s" % self.value

class BaseConst(GenConst):

    def _get_index(self, meth):
        # check whether there is already an index associated to this const
        try:
            index = meth.genconsts[self]
        except KeyError:
            index = len(meth.genconsts)
            meth.genconsts[self] = index
        return index

    def _load_from_array(self, meth, index, clitype):
        meth.il.Emit(OpCodes.Ldarg_0)
        meth.il.Emit(OpCodes.Ldc_I4, index)
        meth.il.Emit(OpCodes.Ldelem_Ref)
        meth.il.Emit(OpCodes.Castclass, clitype)

    def getobj(self):
        raise NotImplementedError

class ObjectConst(BaseConst):

    def __init__(self, obj):
        self.obj = obj

    def getCliType(self):
        if self.obj == ootype.NULL:
            return class2type(cObject)
        cliobj = dotnet.cast_to_native_object(self.obj)
        return cliobj.GetType()

    def getobj(self):
        return self.obj

    def load(self, meth):
        assert False, 'XXX'
##        import pdb;pdb.set_trace()
##        index = self._get_index(builder)
##        if self.obj is None:
##            t = typeof(System.Object)
##        else:
##            t = self.obj.GetType()
##        self._load_from_array(builder, index, t)

    @specialize.arg(1)
    def revealconst(self, T):
        if isinstance(T, ootype.OOType):
            return ootype.cast_from_object(T, self.obj)
        else:
            h = ootype.ooidentityhash(self.obj)
            return lltype.cast_primitive(T, h)


OBJECT = System.Object._INSTANCE
class FunctionConst(BaseConst):

    def __init__(self, delegatetype):
        self.holder = DelegateHolder()
        self.delegatetype = delegatetype

    def getobj(self):
        # XXX: should the conversion be done automatically?
        #return ootype.ooupcast(OBJECT, self.holder)
        return self.holder

    def load(self, meth):
        holdertype = box(self.holder).GetType()
        funcfield = holdertype.GetField('func')
        delegatetype = self.delegatetype
        index = self._get_index(meth)
        self._load_from_array(meth, index, holdertype)
        meth.il.Emit(OpCodes.Ldfld, funcfield)
        meth.il.Emit(OpCodes.Castclass, delegatetype)

    @specialize.arg(1)
    def revealconst(self, T):
        assert isinstance(T, ootype.OOType)
        if isinstance(T, ootype.StaticMethod):
            return unbox(self.holder.GetFunc(), T)
        else:
            assert T is ootype.Object
            return ootype.cast_to_object(self.holder.GetFunc())

class FlexSwitchConst(BaseConst):

    def __init__(self, flexswitch):
        self.flexswitch = flexswitch

    def getobj(self):
        return self.flexswitch

    def load(self, meth):
        index = self._get_index(meth)
        self._load_from_array(meth, index, self.flexswitch.GetType())


class Label(GenLabel):
    def __init__(self, blockid, il_label, inputargs_gv):
        self.blockid = blockid
        self.il_label = il_label
        self.inputargs_gv = inputargs_gv


class RCliGenOp(AbstractRGenOp):

    def __init__(self):
        self.meth = None
        self.il = None
        self.constcount = 0

    @specialize.genconst(1)
    def genconst(self, llvalue):
        T = ootype.typeOf(llvalue)
        if T is ootype.Signed:
            return IntConst(llvalue, cInt32)
        elif T is ootype.Bool:
            return IntConst(int(llvalue), cBoolean)
        elif T is ootype.Char:
            return IntConst(ord(llvalue), cChar)
        elif T is ootype.Float:
            return FloatConst(llvalue)
        elif isinstance(T, ootype.OOType):
            obj = ootype.cast_to_object(llvalue)
            return ObjectConst(obj)
        else:
            assert False, "XXX not implemented"

    @staticmethod
    def genzeroconst(kind):
        if kind is cInt32:
            return IntConst(0, cInt32)
        else:
            return zero_const # ???

    @staticmethod
    @specialize.memo()
    def sigToken(FUNCTYPE):
        """Return a token describing the signature of FUNCTYPE."""
        args = [RCliGenOp.kindToken(T) for T in FUNCTYPE.ARGS]
        res = RCliGenOp.kindToken(FUNCTYPE.RESULT)
        funcclass = classof(FUNCTYPE)
        return SigToken(args, res, funcclass)

    @staticmethod
    def erasedType(T):
        if isinstance(T, lltype.Primitive):
            return lltype.Signed
        elif isinstance(T, ootype.OOType):
            return ootype.Object
        else:
            assert 0, "XXX not implemented"

    @staticmethod
    @specialize.memo()
    def methToken(TYPE, methname):
        return methname #XXX

    @staticmethod
    @specialize.memo()
    def kindToken(T):
        if T is ootype.Void:
            return cVoid
        elif T is ootype.Signed:
            return cInt32
        elif T is ootype.Bool:
            return cBoolean
        elif T is ootype.Float:
            return cDouble
        elif T is ootype.String:
            return cString
        elif T is ootype.Char:
            return cChar
        elif isinstance(T, ootype.OOType):
            return cObject # XXX?
        else:
            assert False

    @staticmethod
    @specialize.memo()
    def fieldToken(T, name):
        _, FIELD = T._lookup_field(name)
        return name #, RCliGenOp.kindToken(FIELD)

    @staticmethod
    @specialize.memo()
    def allocToken(T):
        return RCliGenOp.kindToken(T)

    def check_no_open_mc(self):
        pass

    def newgraph(self, sigtoken, name):
        argsclass = sigtoken.args
        args = new_array(System.Type, len(argsclass)+1)
        args[0] = System.Type.GetType("System.Object[]")
        for i in range(len(argsclass)):
            args[i+1] = class2type(argsclass[i])
        restype = class2type(sigtoken.res)
        delegatetype = class2type(sigtoken.funcclass)
        graph = GraphGenerator(self, name, restype, args, delegatetype)
        builder = graph.branches[0]
        return builder, graph.gv_entrypoint, graph.inputargs_gv[:]


class GraphInfo:
    def __init__(self):
        self.has_flexswitches = False
        self.blocks = [] # blockid -> (meth, label)

class MethodGenerator:
    
    def __init__(self, rgenop, name, restype, args, delegatetype, graphinfo):
        self.rgenop = rgenop
        self.meth_wrapper = get_method_wrapper(name, restype, args)
        self.il = self.meth_wrapper.get_il_generator()
        self.inputargs_gv = []
        # we start from 1 because the 1st arg is an Object[] containing the genconsts
        for i in range(1, len(args)):
            self.inputargs_gv.append(GenArgVar(i, args[i]))
        self.delegatetype = delegatetype
        self.gv_entrypoint = FunctionConst(delegatetype)
        self.genconsts = {}
        self.branches = []
        self.newbranch()
        if restype is not None:
            self.retvar = self.il.DeclareLocal(restype)
        else:
            self.retvar = None
        self.il_retlabel = self.il.DefineLabel()
        self.graphinfo = graphinfo

    def newbranch(self):
        branch = BranchBuilder(self, self.il.DefineLabel())
        self.branches.append(branch)
        return branch

    def newblock(self, args_gv):
        blocks = self.graphinfo.blocks
        blockid = len(blocks)
        result = Label(blockid, self.il.DefineLabel(), args_gv)
        blocks.append((self, result))
        return result

    def emit_code(self):
        # emit initialization code
        self.emit_preamble()
        
        # render all the pending branches
        for branchbuilder in self.branches:
            branchbuilder.replayops()

        # emit dispatch_jump, if there are flexswitches
        self.emit_before_returnblock()

        # render the return block for last, else the verifier could complain        
        self.il.MarkLabel(self.il_retlabel)
        if self.retvar:
            self.il.Emit(OpCodes.Ldloc, self.retvar)
        self.il.Emit(OpCodes.Ret)

        # initialize the array of genconsts
        consts = new_array(System.Object, len(self.genconsts))
        for gv_const, i in self.genconsts.iteritems():
            consts[i] = gv_const.getobj()
        # build the delegate
        myfunc = self.meth_wrapper.create_delegate(self.delegatetype, consts)
        self.gv_entrypoint.holder.SetFunc(myfunc)

    def emit_preamble(self):
        pass

    def emit_before_returnblock(self):
        pass


class GraphGenerator(MethodGenerator):
    def __init__(self, rgenop, name, restype, args, delegatetype):
        graphinfo = GraphInfo()
        MethodGenerator.__init__(self, rgenop, name, restype, args, delegatetype, graphinfo)

    def setup_flexswitches(self):
        if self.graphinfo.has_flexswitches:
            return
        self.graphinfo.has_flexswitches = True
        self.il_dispatch_jump_label = self.il.DefineLabel()
        self.inputargs_clitype = class2type(cInputArgs)
        self.inputargs_var = self.il.DeclareLocal(self.inputargs_clitype)
        self.jumpto_var = self.il.DeclareLocal(class2type(cInt32))

    def emit_preamble(self):
        if not self.graphinfo.has_flexswitches:
            return        
        # InputArgs inputargs_var = new InputArgs()
        clitype = class2type(cInputArgs)
        ctor = clitype.GetConstructor(new_array(System.Type, 0))
        self.il.Emit(OpCodes.Newobj, ctor)
        self.il.Emit(OpCodes.Stloc, self.inputargs_var)

    def emit_before_returnblock(self):
        if not self.graphinfo.has_flexswitches:
            return
        # make sure we don't enter dispatch_jump by mistake
        self.il.Emit(OpCodes.Br, self.il_retlabel)
        self.il.MarkLabel(self.il_dispatch_jump_label)

        il_labels = new_array(System.Reflection.Emit.Label,
                           len(self.graphinfo.blocks))
        for blockid, (builder, label) in self.graphinfo.blocks:
            assert builder is self
            il_labels[blockid] = label.il_label

        self.il.Emit(OpCodes.Ldloc, self.jumpto_var)
        self.il.Emit(OpCodes.Switch, il_labels)
        # XXX: handle blockids that are inside flexswitch cases
        # default: Utils.throwInvalidBlockId(jumpto)
        clitype = class2type(cUtils)
        meth = clitype.GetMethod("throwInvalidBlockId")
        self.il.Emit(OpCodes.Ldloc, self.jumpto_var)
        self.il.Emit(OpCodes.Call, meth)


class BranchBuilder(GenBuilder):

    def __init__(self, meth, il_label):
        self.meth = meth
        self.rgenop = meth.rgenop
        self.il_label = il_label
        self.operations = []
        self.is_open = False
        self.genconsts = meth.genconsts

    def start_writing(self):
        self.is_open = True

    def finish_and_return(self, sigtoken, gv_returnvar):
        op = ops.Return(self.meth, gv_returnvar)
        self.appendop(op)
        self.is_open = False

    def finish_and_goto(self, outputargs_gv, label):
        inputargs_gv = label.inputargs_gv
        assert len(inputargs_gv) == len(outputargs_gv)
        op = ops.FollowLink(self.meth, outputargs_gv,
                            inputargs_gv, label.il_label)
        self.appendop(op)
        self.is_open = False

    @specialize.arg(1)
    def genop1(self, opname, gv_arg):
        opcls = ops.getopclass1(opname)
        op = opcls(self.meth, gv_arg)
        self.appendop(op)
        gv_res = op.gv_res()
        return gv_res
    
    @specialize.arg(1)
    def genop2(self, opname, gv_arg1, gv_arg2):
        opcls = ops.getopclass2(opname)
        op = opcls(self.meth, gv_arg1, gv_arg2)
        self.appendop(op)
        gv_res = op.gv_res()
        return gv_res

    def genop_call(self, sigtoken, gv_fnptr, args_gv):
        op = ops.Call(self.meth, sigtoken, gv_fnptr, args_gv)
        self.appendop(op)
        return op.gv_res()

    def genop_same_as(self, gv_x):
        op = ops.SameAs(self.meth, gv_x)
        self.appendop(op)
        return op.gv_res()

    def genop_oogetfield(self, fieldtoken, gv_obj):
        op = ops.GetField(self.meth, gv_obj, fieldtoken)
        self.appendop(op)
        return op.gv_res()

    def genop_oosetfield(self, fieldtoken, gv_obj, gv_value):
        op = ops.SetField(self.meth, gv_obj, gv_value, fieldtoken)
        self.appendop(op)

    def enter_next_block(self, args_gv):
        seen = {}
        for i in range(len(args_gv)):
            gv = args_gv[i]
            if isinstance(gv, GenConst) or gv in seen:
                op = ops.SameAs(self.meth, gv)
                self.appendop(op)
                args_gv[i] = op.gv_res()
            else:
                seen[gv] = None
        label = self.meth.newblock(args_gv)
        self.appendop(ops.MarkLabel(self.meth, label.il_label))
        return label

    def _jump_if(self, gv_condition, opcode):
        branch = self.meth.newbranch()
        op = ops.Branch(self.meth, gv_condition, opcode, branch.il_label)
        self.appendop(op)
        return branch

    def jump_if_false(self, gv_condition, args_for_jump_gv):
        return self._jump_if(gv_condition, OpCodes.Brfalse)

    def jump_if_true(self, gv_condition, args_for_jump_gv):
        return self._jump_if(gv_condition, OpCodes.Brtrue)

    def flexswitch(self, gv_exitswitch, args_gv):
        # XXX: this code is valid only for GraphGenerator
        self.meth.setup_flexswitches()
        flexswitch = IntFlexSwitch()
        flexswitch.xxxbuilder = self.meth.newbranch()
        gv_flexswitch = flexswitch.gv_flexswitch
        default_branch = self.meth.newbranch()
        label = default_branch.label
        flexswitch.llflexswitch.set_default_blockid(label.blockid)
        op = ops.DoFlexSwitch(self.meth, gv_flexswitch,
                              gv_exitswitch, args_gv)
        self.appendop(op)
        self.is_open = False
        return flexswitch, default_branch

    def appendop(self, op):
        self.operations.append(op)

    def end(self):
        self.meth.emit_code()

    def replayops(self):
        assert not self.is_open
        il = self.meth.il
        il.MarkLabel(self.il_label)
        for op in self.operations:
            op.emit()


class IntFlexSwitch(CodeGenSwitch):

    def __init__(self):
        self.llflexswitch = LowLevelFlexSwitch()
        self.gv_flexswitch = FlexSwitchConst(self.llflexswitch)

    def add_case(self, gv_case):
        return self.xxxbuilder
        #import pdb;pdb.set_trace()



global_rgenop = RCliGenOp()
RCliGenOp.constPrebuiltGlobal = global_rgenop.genconst
zero_const = ObjectConst(ootype.NULL)
