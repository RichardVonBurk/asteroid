#########################################################################
# A tree walker to interpret Asteroid programs
#
# (c) Lutz Hamel, University of Rhode Island
#########################################################################

from copy import deepcopy
from asteroid_state import state
from asteroid_support import assert_match
from asteroid_support import unify
from asteroid_support import map2boolean
from asteroid_support import PatternMatchFailed

#########################################################################
__retval__ = None  # return value register for escaped code

#########################################################################
# Use the exception mechanism to return values from function calls

class ReturnValue(Exception):

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return(repr(self.value))

#########################################################################
class Break(Exception):

    def __str__(self):
        return("break statement exception")

#########################################################################
# exception generated by the throw statement

class ThrowValue(Exception):

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return(repr(self.value))

#########################################################################
def eval_actual_args(args):

    return walk(args)

#########################################################################
def declare_formal_args(unifiers):
    # unfiers is of the format: [ (pattern, term), (pattern, term),...]

    for u in unifiers:
        (pattern, term) = u
        (ID, sym) = pattern
        if ID != 'id':
            raise ValueError("no pattern match possible in function call")
        state.symbol_table.enter_sym(sym, term)

#########################################################################
def handle_dict_ix(val_list, key, value=None, mode="read"):
    # a dictionary is a list of 2-tuples, first component is the key, second
    # component is the value.
    # this function handles both reading and writing dictionary lists

    (KEY_TYPE, key_val) = key

    for ix in range(len(val_list)):
        e = val_list[ix]
        #lhh
        #print(e)

        (LIST, e_list) = e

        if not isinstance(e_list, list):
            raise ValueError("internal error: unsupported dictionary format")

        if len(e_list) != 2:
            raise ValueError("unsupported dictionary format (2)")

        (ENTRY_KEY_TYPE, entry_key) = e_list[0]

        if ENTRY_KEY_TYPE != KEY_TYPE:
            raise ValueError("wrong dictionary key type - expected {} got {}".
                             format(KEY_TYPE, ENTRY_KEY_TYPE))

        if entry_key == key_val: # return the value
            if mode == "read":
                return walk(e_list[1])
            elif mode == "write":
                val_list[ix] = ('tuple', [key, value])
                return val_list
            else:
                raise ValueError("unsupported mode in dictionary handling")

    # fell through the loop -- key doesn't exit
    if mode == "read":
        raise ValueError("dictionary key {} not found".format(key_val))
    elif mode == "write":
        val_list.append(('tuple', [key, value]))
        return val_list
    else:
        raise ValueError("unsupported mode in dictionary handling")

#########################################################################
# we are indexing into the memory of either a list or a constructor to
# read the memory.
#
# NOTE: when indexed with a scalar it will return a single value,
# that value of course could be a list etc.  When index with a list
# then it will return a list of values. Therefore:
#       a@1 =/= a@[1]
# the value on the left of the inequality is a single value, the
# value on the right is a singleton list.
def read_at_ix(structure_val, index):

    (INDEX, ix) = index
    assert_match(INDEX, 'index')

    # find the actual memory we need to access
    # list: return the actual list
    if structure_val[0] in ['list', 'tuple']:
        memory = structure_val[1] # get a reference to the memory
        # compute the index
        ix_val = walk(ix)

    # for objects we access the object memory
    elif structure_val[0] == 'object':
        (OBJECT,
         (CLASS_ID, (ID, class_id)),
         (OBJECT_MEMORY, (LIST, memory))) = structure_val
        # compute the index -- for objects this has to be done
        # in the context of the class scope
        class_val = state.symbol_table.lookup_sym(class_id)
        # unpack the class value
        (CLASS,
         (MEMBER_NAMES, (LIST, member_names)),
         (CLASS_MEMORY, (LIST, class_memory)),
         (CLASS_SCOPE, class_scope)) = class_val
        state.symbol_table.push_scope(class_scope)
        ix_val = walk(ix)
        state.symbol_table.pop_scope()

    # constructor: return the argument list as memory
    elif structure_val[0] == 'apply-list':
        (APPLY_LIST,
         (LIST,
          [(ID, constructor_id),
           (CHILDREN_TYPE, children)])) = structure_val # get a reference to the memory
        if CHILDREN_TYPE != 'tuple':
            # if children is not a tuple make it look like a list
            memory = [(CHILDREN_TYPE, children)]
        else:
            memory = children
        # compute the index
        ix_val = walk(ix)

    else:
        raise ValueError("'{}' is not a structure".format(structure_val[0]))

    # index into memory and get value(s)
    if ix_val[0] == 'integer':
        return memory[ix_val[1]]

    elif ix_val[0] == 'dict-access':
        (DICT_KEY_TYPE, dict_key) = walk(ix_val[1])
        if DICT_KEY_TYPE not in ['integer', 'string']:
            raise ValueError("dictionary key type {} not supported (1)".
                             format(DICT_KEY_TYPE))
        return handle_dict_ix(memory, (DICT_KEY_TYPE, dict_key))

    elif ix_val[0] == 'list':
        if len(ix_val[1]) == 0:
            raise ValueError("index list is empty")

        return_memory = []
        for i in ix_val[1]:
            (IX_EXP_TYPE, ix_exp) = i

            if IX_EXP_TYPE == 'integer':
                return_memory.append(memory[ix_exp])

            elif IX_EXP_TYPE == 'dict-access':
                (DICT_KEY_TYPE, dict_key, *_) = ix_exp
                if DICT_KEY_TYPE not in ['integer', 'string']:
                    raise ValueError("dictionary key type '{}' not supported"\
                                     .format(DICT_KEY_TYPE))
                return_memory.append(handle_dict_ix(memory, (DICT_KEY_TYPE, dict_key)))

            else:
                raise ValueError("unsupported list index")

        return ('list', return_memory)

    else:
        raise ValueError("index op '{}' not supported".format(ix_val[0]))

#########################################################################
# we are indexing into the memory of either a list or a constructor to
# write into the memory.
def store_at_ix(structure_val, index, value):

    (INDEX, ix) = index
    assert_match(INDEX, 'index')

    # find the actual memory we need to access
    # for lists it is just the python list
    if structure_val[0] == 'list':
        memory = structure_val[1]
        # compute the index
        ix_val = walk(ix)

    # for objects we access the object memory
    elif structure_val[0] == 'object':
        (OBJECT,
         (CLASS_ID, (ID, class_id)),
         (OBJECT_MEMORY, (LIST, memory))) = structure_val
        # compute the index -- for objects this has to be done
        # in the context of the class scope
        class_val = state.symbol_table.lookup_sym(class_id)
        # unpack the class value
        (CLASS,
         (MEMBER_NAMES, (LIST, member_names)),
         (CLASS_MEMORY, (LIST, class_memory)),
         (CLASS_SCOPE, class_scope)) = class_val
        state.symbol_table.push_scope(class_scope)
        ix_val = walk(ix)
        state.symbol_table.pop_scope()

    # constructor: return the argument list as memory
    # NOTE: indexing a constructor that is applied to a constant
    #       will fail since there is no memory here.
    elif structure_val[0] == 'apply-list':
        (APPLY_LIST,
         (LIST,
          [(ID, constructor_id),
           (CHILDREN_TYPE, children)])) = structure_val
        if CHILDREN_TYPE != 'tuple':
            # if children is not a tuple make it look like a list
            memory = [(CHILDREN_TYPE, children)]
        else:
            memory = children
        # compute the index
        ix_val = walk(ix)

    else:
        raise ValueError("'{}' is not a structure".format(structure_val[0]))


    # index into memory and set the value
    if ix_val[0] == 'integer':
        memory[ix_val[1]] = value
        return

    elif ix_val[0] == 'dict-access':
        (DICT_KEY_TYPE, dict_key) = walk(ix_val[1])
        if DICT_KEY_TYPE not in ['integer', 'string']:
            raise ValueError("dictionary key type {} not supported (2)".
                             format(DICT_KEY_TYPE))
        return handle_dict_ix(memory, (DICT_KEY_TYPE, dict_key), value, "write")

    elif ix_val[0] == 'list':
        raise ValueError("slicing in patterns not supported")

    else:
        raise ValueError("index op '{}' in patterns not supported"
                         .format(ix_val[0]))

#########################################################################
def handle_call(fval, actual_val_args):

    (FUNCTION, body_list,env) = fval
    assert_match(FUNCTION, 'function')

    #lhh
    #print('in handle_call')
    #print("calling: {}\nwith: {}\n\n".format(fval,actual_val_args))

    # iterate over the bodies to find one that unifies with the actual parameters
    (BODY_LIST, (LIST, body_list_val)) = body_list
    unified = False

    for body in body_list_val:

        (BODY,
         (PATTERN, p),
         (STMT_LIST, stmts)) = body

        try:
            unifiers = unify(actual_val_args, p)
            unified = True
        except PatternMatchFailed:
            unifiers = []
            unified = False

        if unified:
            break

    if not unified:
        raise ValueError("none of the function bodies unified with actual parameters")

    #lhh
    #print("function unified with:")
    #print(unifiers)

    # static scoping for functions!!!
    save_symtab = state.symbol_table.get_config()
    state.symbol_table.set_config(env)
    state.symbol_table.push_scope({})
    declare_formal_args(unifiers)

    # execute the function
    # function calls transfer control - save our caller's lineinfo
    old_lineinfo = state.lineinfo

    try:
        walk(stmts)
    except ReturnValue as val:
        return_value = val.value
    else:
        return_value = ('none', None) # need that in case function has no return statement

    # coming back from a function call - restore caller's lineinfo
    state.lineinfo = old_lineinfo

    # NOTE: popping the function scope is not necessary because we
    # are restoring the original symtab configuration. this is necessary
    # because a return statement might come out of a nested with statement
    state.symbol_table.set_config(save_symtab)

    return return_value

#########################################################################
def declare_unifiers(unifiers):
    # walk the unifiers and bind name-value pairs into the symtab

    # TODO: check for repeated names in the unfiers

    for unifier in unifiers:

        #lhh
        #print("unifier: {}".format(unifier))

        (lval, value) = unifier

        if lval[0] == 'id':
            state.symbol_table.enter_sym(lval[1], value)

        elif lval[0] == 'structure-ix': # list/structure lval access
            # Note: structures have to be declared before index access
            # can be successful!!  They have to be declared so that therefore
            # is memory associated with the structure.

            (STRUCTURE_IX, structure, (INDEX_LIST, (LIST, index_list))) = lval

            # look at the semantics of 'structure'
            structure_val = walk(structure)

            # indexing/slicing
            # iterate over the indexes: ('index', index)
            # NOTE: index operations are left assoc. each index op produces
            # a new memory object cast as a list.  this memory object
            # is fed to the following index op.  here is last index
            # updates the memory of the object.
            for ix_ix in range(0, len(index_list)-1):
                structure_val = read_at_ix(structure_val, index_list[ix_ix])

            # use the last index to update the memory
            store_at_ix(structure_val, index_list[-1], value)

        else:
            raise ValueError("unknown unifier type '{}'".format(lval[0]))

#########################################################################
# node functions
#########################################################################
def global_stmt(node):

    (GLOBAL, (LIST, id_list)) = node
    assert_match(GLOBAL, 'global')
    assert_match(LIST, 'list')

    for id_tuple in id_list:
        (ID, id_val) = id_tuple
        if state.symbol_table.is_symbol_local(id_val):
            raise ValueError("{} is already local, cannot be declared global"
                             .format(id_val))
        state.symbol_table.enter_global(id_val)

#########################################################################
def assert_stmt(node):

    (ASSERT, exp) = node
    assert_match(ASSERT, 'assert')

    exp_val = walk(exp)
    # mapping asteroid assert into python assert
    assert exp_val[1], 'assert failed'

#########################################################################
def attach_stmt(node):

    (ATTACH, (FUN_EXP, fexp), (CONSTR_ID, sym)) = node
    assert_match(ATTACH, 'attach')
    assert_match(FUN_EXP, 'fun-exp')
    assert_match(CONSTR_ID, 'constr-id')

    fval = walk(fexp)

    if fval[0] != 'function':
        raise ValueError("expected a function in attach for '{}'"
                         .format(sym))
    else:
        state.symbol_table.attach_to_sym(sym, fval)

#########################################################################
def detach_stmt(node):

    (DETACH, (ID, id)) = node
    assert_match(DETACH, 'detach')

    state.symbol_table.detach_from_sym(id)

#########################################################################
def unify_stmt(node):

    (UNIFY, pattern, exp) = node
    assert_match(UNIFY, 'unify')

    term = walk(exp)
    unifiers = unify(term, pattern)
    declare_unifiers(unifiers)

#########################################################################
def return_stmt(node):

    (RETURN, e) = node
    assert_match(RETURN, 'return')

    raise ReturnValue(walk(e))

#########################################################################
def break_stmt(node):

    (BREAK,) = node
    assert_match(BREAK, 'break')

    raise Break()

#########################################################################
def throw_stmt(node):

    (THROW, object) = node
    assert_match(THROW, 'throw')

    raise ThrowValue(walk(object))

#########################################################################
def try_stmt(node):

    (TRY,
     (STMT_LIST, try_stmts),
     (CATCH_LIST, (LIST, catch_list))) = node

    try:
        walk(try_stmts)

    # NOTE: in Python the 'as inst' variable is only local to the catch block???
    except ThrowValue as inst:
        except_val = inst.value
        inst_val = inst

    except ReturnValue as inst:
        # return values should never be captured by user level try stmts - rethrow
        raise inst

    except PatternMatchFailed as inst:
        # convert a Python string to an Asteroid string
        except_val = ('tuple',
                      [('string', 'PatternMatchFailed'), ('string', inst.value)])
        inst_val = inst

    except Exception as inst:
        # convert exception args to an Asteroid string
        except_val = ('tuple',
                      [('string', 'Exception'), ('string', str(inst))])
        inst_val = inst

    else:
        # no exceptions found in the try statements
        return

    # we had an exception - walk the catch list and find an appropriate set of
    # catch statements.
    for catch_val in catch_list:
        (CATCH,
         (CATCH_PATTERN, catch_pattern),
         (CATCH_STMTS, catch_stmts)) = catch_val
        try:
            unifiers = unify(except_val, catch_pattern)
        except PatternMatchFailed:
            pass
        else:
            declare_unifiers(unifiers)
            walk(catch_stmts)
            return

    # no exception handler found - rethrow the exception
    raise inst_val

#########################################################################
def while_stmt(node):

    (WHILE, cond_exp, body_stmts) = node
    assert_match(WHILE, 'while')

    (COND_EXP, cond) = cond_exp
    (STMT_LIST, body) = body_stmts

    try:
        (COND_TYPE, cond_val) = map2boolean(walk(cond))
        while cond_val:
            walk(body)
            (COND_TYPE, cond_val) = map2boolean(walk(cond))
    except Break:
        pass

#########################################################################
def repeat_stmt(node):

    (REPEAT, body_stmts, cond_exp) = node
    assert_match(REPEAT, 'repeat')

    (COND_EXP, cond) = cond_exp
    (STMT_LIST, body) = body_stmts

    try:
        while True:
            walk(body)
            (COND_TYPE, cond_val) = map2boolean(walk(cond))
            if cond_val:
                break

    except Break:
        pass

#########################################################################
def for_stmt(node):

    (FOR, (IN_EXP, in_exp), (STMT_LIST, stmt_list)) = node
    assert_match(FOR, 'for')

    (IN, pattern, list_term) = in_exp

    # expand the list_term in case the list is expressed as a constructor
    (LIST, list_val) = walk(list_term)

    # for each term on the list unfiy with pattern, declare the bound variables,
    # and execute the loop body in that context
    # NOTE: just like Python, loop bodies do not create a new scope!
    # NOTE: we can use unification as a filter of elements:
    #
    #      for (2,y) in [(1,11), (1,12), (1,13), (2,21), (2,22), (2,23)]  do
    #             print y.
    #      end for
    try:
        for term in list_val:
            try:
                unifiers = unify(term,pattern)
            except PatternMatchFailed:
                pass
            else:
                declare_unifiers(unifiers)
                walk(stmt_list)
    except Break:
        pass

#########################################################################
def if_stmt(node):

    (IF, (LIST, if_list)) = node
    assert_match(IF, 'if')
    assert_match(LIST, 'list')

    for if_clause in if_list:

        (IF_CLAUSE,
         (COND, cond),
         (STMT_LIST, stmts)) = if_clause

        (BOOLEAN, cond_val) = map2boolean(walk(cond))

        if cond_val:
            walk(stmts)
            break

#########################################################################
def class_def_stmt(node):

    (CLASS_DEF, (ID, class_id), (MEMBER_LIST, (LIST, member_list))) = node
    assert_match(CLASS_DEF, 'class-def')
    assert_match(ID, 'id')
    assert_match(MEMBER_LIST, 'member-list')
    assert_match(LIST, 'list')

    # declare members
    # member names are declared as variables whose value is the slot
    # in a class object
    class_memory = [] # this will serve as a template for instanciating objects
    member_names = []
    class_scope = {}
    state.symbol_table.push_scope(class_scope)

    for member_ix in range(len(member_list)):
        member = member_list[member_ix]
        if member[0] == 'data':
            (DATA,
             (ID, member_id),
             (INIT_VAL, value)) = member
            state.symbol_table.enter_sym(member_id, ('integer', member_ix))
            class_memory.append(walk(value))
            member_names.append(member_id)
        elif member[0] == 'unify':
            (UNIFY, (ID, member_id), function_value) = member
            state.symbol_table.enter_sym(member_id, ('integer', member_ix))
            class_memory.append(walk(function_value))
            member_names.append(member_id)
        else:
            raise ValueError("unsupported class member '{}'".format(member[0]))

    state.symbol_table.pop_scope()

    class_type = ('class',
                  ('member-names', ('list', member_names)),
                  ('class-memory', ('list', class_memory)),
                  ('class-scope', class_scope))

    state.symbol_table.enter_sym(class_id, class_type)

#########################################################################
def apply_list_exp(node):

    (APPLY_LIST, (LIST, apply_list)) = node
    assert_match(APPLY_LIST, 'apply-list')

    # handle a list of apply terms:
    # e.g. inc inc 1
    # function application happens from right to left, therefore we reverse
    # a shallow copy of the apply-list
    rev_list = list(apply_list)
    rev_list.reverse()

    #lhh
    #print("rev-list: {}".format(rev_list))

    # first element must be a value to pass to a function
    arg_val = walk(rev_list[0])

    #lhh
    #print("arg_val: {}".format(arg_val))

    # step thru all the apply terms each of which needs to produce a
    # function/constructor value - the current function application
    # will produce the input value (arg_val) for the next application
    for apply_ix in range(1, len(rev_list)):
        ftree = rev_list[apply_ix]
        fval = walk(ftree)

        # object member function
        # NOTE: object member functions and functions that are embedded
        #       in a term structure built from constructors look the
        #       the same, but only object member functions are passed
        #       an object reference.
        if fval[0] == 'function' and ftree[0] == 'structure-ix':
            (STRUCTURE_IX, obj_tree, index_list) = ftree
            obj_ref = walk(obj_tree)
            if obj_ref[0] == 'object': # insert object ref
                if arg_val[0] == 'none':
                    arg_val = handle_call(fval, obj_ref)
                elif arg_val[0] != 'tuple':
                    new_arg_val = ('tuple', [obj_ref, arg_val])
                    arg_val = handle_call(fval, new_arg_val)
                elif arg_val[0] == 'tuple':
                    arg_val[1].insert(0, obj_ref)
                    arg_val = handle_call(fval, arg_val)
                else:
                    raise ValueError(
                        "unknown parameter type '{}' in apply"
                        .format(arg_val[0]))
            else: # it is a function embedded in a term structure - just call it
                arg_val = handle_call(fval, arg_val)

        # regular function call
        elif fval[0] == 'function':
            arg_val = handle_call(fval, arg_val)

        # constructor call
        elif fval[0] == 'constructor': # return structure
            (ID, constructor_id) = ftree
            (ARITY, arity) = fval[1]
            # check arity match
            if arg_val[0] == 'none' and arity != 0:
                raise ValueError(
                    "constructor '{}' arity mismatch, expected {} got 0"
                    .format(constructor_id, arity))
            elif arg_val[0] == 'tuple' and (len(arg_val[1]) != arity) :
                raise ValueError(
                    "constructor '{}' arity mismatch, expected {} got {}"
                    .format(constructor_id, arity, len(arg_val[1])))
            elif arg_val[0] != 'tuple' and arity != 1:
                raise ValueError(
                    "constructor '{}' arity mismatch, expected {} got 1"
                    .format(constructor_id, arity))

            arg_val = ('apply-list', ('list', [(ID, constructor_id), arg_val]))

        # class constructor call
        elif fval[0] == 'class':
            (ID, class_id) = ftree
            (CLASS,
             (MEMBER_NAMES, (LIST, member_names)),
             (CLASS_MEMORY, (LIST, class_memory)),
             (CLASS_SCOPE, class_scope)) = fval

            # create our object memory - memory cells now have initial values
            # need to make a deep copy
            object_memory = deepcopy(class_memory)
            # create our object
            obj_ref = ('object',
                      ('class-id', ('id', class_id)),
                      ('object-memory', ('list', object_memory)))
            # if the class has an __init__ function call it on the object
            # NOTE: constructor functions do not have return values.
            if '__init__' in member_names:
                slot_ix = member_names.index('__init__')
                init_fval = class_memory[slot_ix]
                # calling a member function - push class scope
                state.symbol_table.push_scope(class_scope)
                if arg_val[0] == 'none':
                    handle_call(init_fval, obj_ref)
                elif arg_val[0] != 'tuple':
                    arg_val = ('tuple', [obj_ref, arg_val])
                    handle_call(init_fval, arg_val)
                elif arg_val[0] == 'tuple':
                    arg_val[1].insert(0, obj_ref)
                    handle_call(init_fval, arg_val)
                state.symbol_table.pop_scope()

            # return the new object as the next arg_val
            arg_val = obj_ref

        else:
            raise ValueError("unknown apply term '{}'".format(fval[0]))

    return arg_val

#########################################################################
def structure_ix_exp(node):

    (STRUCTURE_IX, structure, (INDEX_LIST, (LIST, index_list))) = node

    assert_match(STRUCTURE_IX, 'structure-ix')
    assert_match(INDEX_LIST, 'index-list')
    assert_match(LIST, 'list')

    # look at the semantics of 'structure'
    structure_val = walk(structure)

    # indexing/slicing
    # iterate over the indexes: ('index', index)
    # NOTE: index operations are left assoc. each index op produces
    # a new memory object cast as a list.  this memory object
    # is fed to the following index op.
    for ix_ix in range(0, len(index_list)):
        structure_val = read_at_ix(structure_val, index_list[ix_ix])

    return structure_val

#########################################################################
def list_exp(node):

    (LIST, inlist) = node
    assert_match(LIST, 'list')

    outlist =[]

    for e in inlist:
        outlist.append(walk(e))

    return ('list', outlist)

#########################################################################
def tuple_exp(node):

    (TUPLE, intuple) = node
    assert_match(TUPLE, 'tuple')

    outtuple = []

    for e in intuple:
        outtuple.append(walk(e))

    return ('tuple', outtuple)

#########################################################################
def escape_exp(node):

    (ESCAPE, s) = node
    assert_match(ESCAPE, 'escape')

    global __retval__
    __retval__ = ('none', None)

    exec(s)

    return __retval__

#########################################################################
def is_exp(node):

    (IS, term, pattern) = node
    assert_match(IS, 'is')

    term_val = walk(term)

    try:
        unifiers = unify(term_val, pattern)
    except PatternMatchFailed:
        return ('boolean', False)
    else:
        declare_unifiers(unifiers)
        return ('boolean', True)

#########################################################################
def in_exp(node):

    (IN, exp, exp_list) = node
    assert_match(IN, 'in')

    exp_val = walk(exp)
    (EXP_LIST_TYPE, exp_list_val, *_) = walk(exp_list)

    if EXP_LIST_TYPE != 'list':
        raise ValueError("right argument to in operator has to be a list")

    # we simply map our in operator to the Python in operator
    if exp_val in exp_list_val:
        return ('boolean', True)
    else:
        return ('boolean', False)

#########################################################################
def otherwise_exp(node):

    (OTHERWISE, e1, e2) = node
    assert_match(OTHERWISE, 'otherwise')

    val = walk(e1)

    if val[0] == 'none':
        return walk(e2)
    else:
        return val

#########################################################################
def if_exp(node):

    (IF_EXP, cond_exp, then_exp, else_exp) = node
    assert_match(IF_EXP, 'if-exp')

    (BOOLEAN, cond_val) = map2boolean(walk(cond_exp))

    if cond_val:
        return walk(then_exp)
    else:
        return walk(else_exp)

#########################################################################
# NOTE: 'to-list' is not a semantic value and should never appear in
#       any tests.  It is a constructor and should be expanded by the
#       walk function before semantic processing.
def to_list_exp(node):

    (TOLIST,
     (START, start),
     (STOP, stop),
     (STEP, step)) = node

    assert_match(TOLIST, 'to-list')
    assert_match(START, 'start')
    assert_match(STOP, 'stop')
    assert_match(STEP, 'step')

    (START_TYPE, start_val, *_) = walk(start)
    (STOP_TYPE, stop_val, *_) = walk(stop)
    (STEP_TYPE, step_val, *_) = walk(step)

    if START_TYPE != 'integer' or STOP_TYPE != 'integer' or STEP_TYPE != 'integer':
        raise ValueError("only integer values allowed in start, stop, or step")

    out_list_val = []

    # TODO: check out the behavior with step -1 -- is this what we want?
    # the behavior is start and stop included
    if int(step_val) > 0: # generate the list
        ix = int(start_val)
        while ix <= int(stop_val):
            out_list_val.append(('integer', ix))
            ix += int(step_val)

    elif int(step_val) == 0: # error
        raise ValueError("step size of 0 not supported")

    elif int(step_val) < 0: # generate the list
        ix = int(start_val)
        while ix >= int(stop_val):
            out_list_val.append(('integer', ix))
            ix += int(step_val)

    else:
        raise ValueError("{} not a valid step value".format(step_val))

    return ('list', out_list_val)

#########################################################################
# NOTE: this is the value view of the head tail constructor, for the
#       pattern view of this constructor see unify.
def head_tail_exp(node):

    (HEAD_TAIL, head, tail) = node
    assert_match(HEAD_TAIL, 'head-tail')

    head_val = walk(head)
    (TAIL_TYPE, tail_val) = walk(tail)

    if TAIL_TYPE != 'list':
        raise ValueError(
            "unsuported tail type {} in head-tail operator".
            format(TAIL_TYPE))

    return ('list', [head_val] + tail_val)

#########################################################################
def process_lineinfo(node):

    (LINEINFO, lineinfo_val) = node
    assert_match(LINEINFO, 'lineinfo')

    #lhh
    #print("lineinfo: {}".format(lineinfo_val))

    state.lineinfo = lineinfo_val

#########################################################################
# walk
#########################################################################
def walk(node):
    # node format: (TYPE, [child1[, child2[, ...]]])
    type = node[0]

    if type in dispatch_dict:
        node_function = dispatch_dict[type]
        return node_function(node)
    else:
        raise ValueError("feature {} not yet implemented".format(type))

# a dictionary to associate tree nodes with node functions
dispatch_dict = {
    # statements - statements do not produce return values
    'lineinfo'      : process_lineinfo,
    'noop'          : lambda node : None,
    'assert'        : assert_stmt,
    'attach'        : attach_stmt,
    'detach'        : detach_stmt,
    'unify'         : unify_stmt,
    'while'         : while_stmt,
    'repeat'        : repeat_stmt,
    'for'           : for_stmt,
    'global'        : global_stmt,
    'return'        : return_stmt,
    'break'         : break_stmt,
    'if'            : if_stmt,
    'throw'         : throw_stmt,
    'try'           : try_stmt,
    'class-def'     : class_def_stmt,
    # expressions - expressions do produce return values
    'list'          : list_exp,
    'tuple'         : tuple_exp,
    'to-list'       : to_list_exp,
    'head-tail'     : head_tail_exp,
    'raw-to-list'   : lambda node : walk(('to-list', node[1], node[2], node[3])),
    'raw-head-tail' : lambda node : walk(('head-tail', node[1], node[2])),
    'dict-access'   : lambda node : node,
    'seq'           : lambda node : ('seq', walk(node[1]), walk(node[2])),
    'none'          : lambda node : node,
    'nil'           : lambda node : node,
    'function-decl' : lambda node : ('function',node[1],state.symbol_table.get_config()),
    'function'      : lambda node : node, # looks like a constant
    'constructor'   : lambda node : node, # looks like a constant
    'string'        : lambda node : node,
    'integer'       : lambda node : node,
    'real'          : lambda node : node,
    'boolean'       : lambda node : node,
    # quoted code should be treated like a constant if not ignore_quote
    'quote'         : lambda node : walk(node[1]) if state.ignore_quote else node,
    # type tag used in conjunction with escaped code in order to store
    # foreign objects in Asteroid data structures
    'foreign'       : lambda node : node,
    'id'            : lambda node : state.symbol_table.lookup_sym(node[1]),
    'apply-list'    : apply_list_exp,
    'structure-ix'  : structure_ix_exp,
    'escape'        : escape_exp,
    'is'            : is_exp,
    'in'            : in_exp,
    'otherwise'     : otherwise_exp,
    'if-exp'        : if_exp,
}
