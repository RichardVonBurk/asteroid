#########################################################################
# A tree walker to interpret Asteroid programs
#
# (c) 2018 - Lutz Hamel, University of Rhode Island
#########################################################################

from asteroid_state import state
from asteroid_support import assert_match
from asteroid_support import unify
from asteroid_support import promote
from pprint import pprint

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
def eval_actual_args(args):

    return walk(args)

#########################################################################
def declare_formal_args(unifiers):
    # unfiers is of the format: [ (pattern, term), (pattern, term),...]

    for u in unifiers:
        pattern, term = u
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
        print(e)

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
                val_list[ix] = ('list', [key, value])
                return val_list
            else:
                raise ValueError("unsupported mode in dictionary handling")

    if mode == "read":
        raise ValueError("dictionary key {} not found".format(key))
    elif mode == "write":
        val_list.append(('list', [key, value]))
        return val_list
    else:
        raise ValueError("unsupported mode in dictionary handling")

#########################################################################
# handle list index expressions as rvals
def handle_list_ix(list_val, ix):

    (VAL_LIST, ll) = list_val
    (IX_TYPE, ixs, *_) = ix

    if VAL_LIST not in ['list', 'raw-list']:
        raise ValueError(
            "expected list node but got {} node".
            format(VAL_LIST))

    # NOTE: no longer supported -- everything is now a list of indexes
    #if IX_TYPE == 'integer': # then ixs is an integer index
    #   ix_val = int(ixs)
    #   return ll[ix_val]
        
    if IX_TYPE in ['list', 'raw-list']: # then ixs is a list of indexes
        if len(ixs) == 0:
            raise ValueError("index list is empty")

        new_l = [] # construct a list of return values
        for i in ixs:
            (IX_EXP_TYPE, ix_exp) = walk(i)

            if IX_EXP_TYPE == 'integer':
                ix_exp_val = int(ix_exp)
                new_l.append(walk(ll[ix_exp_val]))

            elif IX_EXP_TYPE == 'dict-access':
                (DICT_KEY_TYPE, dict_key, *_) = walk(ix_exp)
                if DICT_KEY_TYPE not in ['integer', 'string']:
                    raise ValueError("dictionary key type {} not supported".
                                     format(DICT_KEY_TYPE))
                new_l.append(handle_dict_ix(ll, (DICT_KEY_TYPE, dict_key)))

            else:
                raise ValueError("unsupported list index")

        if len(new_l) == 1: # return scalar value
            return new_l[0]
        else:
            return ('list', new_l)

    else:
        raise ValueError("index op {} not yet implemented".format(ix[0]))

#########################################################################
# recursively walk through the contents of a list together with the
# index expression and find the element to store into
#
# NOTE: the key here is that list names in Python are treated as references,
# that is, even though we are working outside the symbol table, the 
# symbol table holds a reference to the list we are updating so writing
# to the list here will update the list in the symbol table.
# the list acts like memory associated with the list name
def store_into_list(list_val, ix, value):

    (INDEX, ix_exp, rest_ix) = ix
    assert_match(INDEX, 'index')

    # evaluate ix_exp and use it to update list element
    (LIST, ix_val_list) = walk(ix_exp)

    if LIST not in ['list', 'raw-list']:
        raise ValueError("unknown index expression")

    if len(ix_val_list) != 1:
        raise ValueError("list slicing not supported on unification")

    (TYPE, ix_val) = ix_val_list[0]

    if TYPE == 'integer':
        ix_val = int(ix_val)

        if rest_ix[0] == 'nil': # store into list element
            list_val[ix_val] = value

        else: # keep recursing
            nested_list = list_val[ix_val]
            (TYPE, val) = nested_list
            if TYPE not in ['list', 'raw-list']:
                raise ValueError("list and index expression do not match")
            else:
                store_into_list(val, rest_ix, value)
        
    elif TYPE == 'dict-access':
        (KEY_TYPE, key, *_) = walk(ix_val) # compute the semantics of the dictionary key
        if KEY_TYPE not in ['integer', 'string']:
            raise ValueError("dictionary key type {} not supported".
                             format(KEY_TYPE))

        if rest_ix[0] == 'nil': # store into list element
            handle_dict_ix(list_val, (KEY_TYPE, key), value, mode="write")

        else: # keep recursing
            nested_list = handle_dict_ix(list_val, (KEY_TYPE, key))
            (TYPE, val) = nested_list
            if TYPE not in ['list', 'raw-list']:
                raise ValueError("list and index expression do not match")
            else:
                store_into_list(val, rest_ix, value)
        
    else:
        raise ValueError("unsupported list index expression")

#########################################################################
# handle list index expressions as lvals -- compute the list lval from
# sym and ix and unify to it the value
def handle_list_ix_lval(sym, ix, value):
    
    sym_list_val = state.symbol_table.lookup_sym(sym)

    (TYPE, val) = sym_list_val

    if TYPE not in ['list', 'raw-list']:
        raise ValueError("{} is not of type list".format(sym))

    store_into_list(val, ix, value)

#########################################################################
def update_struct_sym(sym, ix, value):

    # check out the index -- needs to evaluate to the value 0.
    (INDEX, ix_exp, rest_ix) = ix
    assert_match(INDEX, 'index')

    (LIST, ix_val_list) = walk(ix_exp)

    if LIST not in ['list', 'raw-list']:
        raise ValueError("unknown index expression")

    if len(ix_val_list) != 1:
        raise ValueError("list slicing not supported on unification")

    (TYPE, ix_val) = ix_val_list[0]

    if TYPE != 'integer':
        raise ValueError("non-integer list index expression")
    else:
        ix_val = int(ix_val)
        if ix_val != 0:
            raise ValueError("index and arity of structure mismatched - expected index 0")

    # update the object structure in the symbol table

    sym_val = state.symbol_table.lookup_sym(sym)

    # check that we are dealing with a constructor type
    (APPLY, (ID, structsym), obj_structure) = sym_val
    structsym_val = state.symbol_table.lookup_sym(structsym)
    if structsym_val[0] != 'constructor':
        raise ValueError("{} is not a constructor".format(structsym))

    # get arity of constructor
    (CONSTRUCTOR, (ARITY, aval_str)) = structsym_val
    aval = int(aval_str)
    if aval != 1:
        raise ValueError("internal interpreter error - arity mismatch on struct lval")

    # construct a new structure based on the new value and update sym
    new_struct = ('apply',
                  ('id', structsym),
                  ('apply',
                   value,
                   ('nil',)))

    state.symbol_table.update_sym(sym, new_struct)
    

#########################################################################
# handle structure index expressions as lvals -- compute the structure lval from
# sym and ix and unify to it the value
def handle_struct_ix_lval(sym, ix, value):
    
    sym_val = state.symbol_table.lookup_sym(sym)

    # check that we are dealing with a constructor type
    (APPLY, (ID, structsym), obj_structure) = sym_val
    structsym_val = state.symbol_table.lookup_sym(structsym)
    if structsym_val[0] != 'constructor':
        raise ValueError("{} is not a constructor".format(structsym))

    # get arity of constructor
    (CONSTRUCTOR, (ARITY, arity_str)) = structsym_val
    arity_val = int(arity_str)
    
    # get the list from the structure that actually holds the values of the object
    (APPLY, (CONTENT_TYPE, content), NIL) = obj_structure

    if CONTENT_TYPE in ['list', 'raw-list']:
        if len(content) != arity_val:
            raise ValueError(
                "constructor arity does not match arguments - expected {} got {}".
                format(arity_val, len(content)))

        store_into_list(content, ix, value)

    else:
        if arity_val != 1:
            raise ValueError(
                "constructor arity does not match arguments - expected {} got {}".
                format(arity_val, len(content)))

        # update symbol in symtab with new structure content
        update_struct_sym(sym, ix, value)

#########################################################################
def handle_call(fval, actual_arglist):
    
    if fval[0] != 'function':
        raise ValueError("not a function in call")

    actual_val_args = eval_actual_args(actual_arglist)   # evaluate actuals in current symtab
    body_list = fval[1]   # get the list of function bodies - nil terminated seq list

    # iterate over the bodies to find one that unifies with the actual parameters
    (BODY_LIST, body_list_ix) = body_list
    unified = False

    while body_list_ix[0] != 'nil':
        (SEQ, body, next) = body_list_ix

        (BODY, 
         (PATTERN, p),
         (STMT_LIST, stmts)) = body

        try:
            unifiers = unify(actual_val_args, p)
            unified = True
        except:
            unifiers = []
            unified = False

        if unified:
            break
        else:
            body_list_ix = next

    if not unified:
        ValueError("none of the function bodies unified with actual parameters")

    # dynamic scoping for functions!!!
    state.symbol_table.push_scope()
    declare_formal_args(unifiers)

    # execute the function
    try:
        walk(stmts)         
    except ReturnValue as val:
        return_value = val.value
    else:
        return_value = ('none',) # need that in case function has no return statement

    # return to the original scope
    state.symbol_table.pop_scope()

    return return_value

#########################################################################
def declare_unifiers(unifiers):
    # walk the unifiers and bind name-value pairs into the symtab

    # TODO: check for repeated names in the unfiers
    # TODO: deal with non-local variables

    for unifier in unifiers:

        #lhh
        #print("unifier: {}".format(unifier))

        (lval, value) = unifier

        if lval[0] == 'id':
            state.symbol_table.enter_sym(lval[1], value)

        elif lval[0] == 'structure-ix': # list/structure lval access
            (STRUCTUREIX, (ID, sym), ix) = lval
            (symtype, symval, *_) = state.symbol_table.lookup_sym(sym)

            if symtype in ['list', 'raw-list']:
                handle_list_ix_lval(sym, ix, value)

            elif symtype == 'apply':
                handle_struct_ix_lval(sym, ix, value)

            else:
                raise ValueError("unknown type {} in unification lval".format(symtype))

        else:
            raise ValueError("unknown unifier type {}".format(lval[0]))

#########################################################################
# node functions
#########################################################################
def attach_stmt(node):

    (ATTACH, f, (CONSTR_ID, sym)) = node
    assert_match(ATTACH, 'attach')
    assert_match(CONSTR_ID, 'constr-id')

    if f[0] == 'fun-id':
        fval = state.symbol_table.lookup_sym(f[1])
    elif f[0] == 'fun-const':
        fval = f[1]
    else:
        raise ValueError("unknown function in attach")

    if fval[0] != 'function':
        raise ValueError("{} is not a function".format(f[1]))
    else:
        state.symbol_table.attach_to_sym(sym, fval)

#########################################################################
def unify_stmt(node):

    (UNIFY, pattern, exp) = node
    assert_match(UNIFY, 'unify')
    
    term = walk(exp)
    unifiers = unify(term, pattern)

    declare_unifiers(unifiers)


#########################################################################
def get_stmt(node):

    (GET, name) = node
    assert_match(GET, 'get')

    s = input("Value for " + name + '? ')
    
    try:
        value = int(s)
    except ValueError:
        raise ValueError("expected an integer value for " + name)
    
    state.symbol_table.update_sym(name, ('scalar', value))

#########################################################################
def print_stmt(node):

    # TODO: deal with files and structures/lists

    (PRINT, exp, f) = node
    assert_match(PRINT, 'print')
    
    value = walk(exp)
    print("{}".format(value))

#########################################################################
def call_stmt(node):

    (CALLSTMT, name, actual_args) = node
    assert_match(CALLSTMT, 'callstmt')

    handle_call(name, actual_args)

#########################################################################
def return_stmt(node):

    (RETURN, e) = node
    assert_match(RETURN, 'return')

    if e[0] == 'nil': # no return value
        raise ReturnValue(('none',))

    else:
        raise ReturnValue(walk(e))

#########################################################################
def while_stmt(node):

    (WHILE, cond, body) = node
    assert_match(WHILE, 'while')
    
    value = walk(cond)
    while value != 0:
        walk(body)
        value = walk(cond)

#########################################################################
def if_stmt(node):
    
    try: # try the if-then pattern
        (IF, cond, then_stmt, (NIL,)) = node
        assert_match(IF, 'if')
        assert_match(NIL, 'nil')

    except ValueError: # if-then pattern didn't match
        (IF, cond, then_stmt, else_stmt) = node
        assert_match(IF, 'if')
        
        value = walk(cond)
        
        if value != 0:
            walk(then_stmt)
        else:
            walk(else_stmt)

    else: # if-then pattern matched
        value = walk(cond)
        if value != 0:
            walk(then_stmt)

#########################################################################
def block_stmt(node):
    
    (BLOCK, stmt_list) = node
    assert_match(BLOCK, 'block')
    
    state.symbol_table.push_scope()
    walk(stmt_list)
    state.symbol_table.pop_scope()

#########################################################################
def apply_exp(node):
    # could be a call: fval fargs
    # could be a constructor invocation for an object: B(a,b,c)

    #lhh
    #print("node: {}".format(node))

    (APPLY, val, args) = node
    assert_match(APPLY, 'apply')

    if args[0] == 'nil':
        # we are looking at the last apply node in
        # a cascade of apply nodes
        return walk(val)

    # more 'apply' nodes
    (APPLY, parms, rest) = args
    assert_match(APPLY, 'apply')

    # look at the semantics of val
    v = walk(val)

    if v[0] == 'function': # execute a function call
        # if it is a function call then the args node is another
        # 'apply' node
        return walk(('apply', handle_call(v, parms), rest))

    elif v[0] == 'constructor': # return the structure
        (ID, constr_sym) = val
        assert_match(ID, 'id') # name of the constructor

        # get arity of constructor
        (CONSTRUCTOR, (ARITY, arity)) = v
        arity_val = int(arity)

        # constructor apply nodes come in 2 flavors, in both cases we preserve
        # the toplevel structure and walk the args in case the args are functions
        # or operators that compute new structure...
        # 1) (apply, parms, nil) -- single call
        if rest[0] == 'nil':  
            (parm_type, parm_val) = parms
            if parm_type in ['list', 'raw-list']:
                if len(parm_val) != arity_val:
                    raise ValueError(
                        "argument does not match constructor arity - expected {} got {}".
                        format(arity_val, len(parm_val)))
            else:
                if arity_val != 1:
                    raise ValueError(
                        "argument does not match constructor arity - expected {} got 1".
                        format(arity_val))

            return ('apply', 
                    ('id', constr_sym),
                    ('apply', walk(parms), rest))

        # 2) (apply, e1, (apply, e2, rest)) -- cascade
        else:
            if arity_val != 1:
                raise ValueError(
                    "argument does not match constructor arity - expected {} argument(s)".format(
                        arity_val))

            return ('apply', 
                    ('id', constr_sym),
                    walk(args))

    else: # not implemented
        raise ValueError("'apply' not implemented for {}".format(v[0]))

#########################################################################
def structure_ix_exp(node):
    # list/struct access: x@[0]

    #lhh
    #print("structure node: {}".format(node))

    (STRUCTUREIX, val, args) = node
    assert_match(STRUCTUREIX, 'structure-ix')
    
    if args[0] == 'nil':
        return walk(val)
    else:
        (INDEX, ix, rest) = args
        assert_match(INDEX, 'index')

    # look at the semantics of val
    v = walk(val)

    # indexing/slicing a list
    if v[0] in ['list', 'raw-list']:
        # if it is a list then the args node is another
        # 'apply' node for indexing the list
        (INDEX, ix, rest) = args
        assert_match(INDEX, 'index')
        return walk(('structure-ix', handle_list_ix(v, walk(ix)), rest))

    # indexing/slicing a structure of the form A(x,y,z)
    elif v[0] == 'apply': 
        # we are looking at something like this
        #    (0:'apply', 
        #     1:(0:'id', 
        #        1:struct_sym),
        #     2:next))

        # find out if the id in the structure represents a constructor
        if v[1][0] != 'id':
            raise ValueError(
                'illegal value in structure index/slicing, expected id found {}'.format(
                    v[1][0]))
        constructor_sym = v[1][1]
        (TYPE, cval, *_) = state.symbol_table.lookup_sym(constructor_sym)
        if TYPE != 'constructor':
            raise ValueError("symbol {} needs to be a constructor".format(constructor_sym))

        # get the arity
        (ARITY, arity_val) = cval
        arity_val = int(arity_val)

        # get the part of the structure that actually stores the info - a list or a single value
        (APPLY, sargs, next) = v[2]
        assert_match(APPLY, 'apply')
        if sargs[0] in ['list', 'raw-list']:
            (INDEX, ix, rest) = args
            assert_match(INDEX, 'index')
            # make the result look like a structure index in case we get a structure back
            # that we need to index again, e.g., a@[x]@[y]
            return walk(('structure-ix', handle_list_ix(sargs, walk(ix)), rest))
        
        else: # just a single element
            if arity_val != 1:
                raise ValueError(
                    "illegal index expression for structure {}".format(
                        constructor_sym))
            # map the single member into a singleton list so we can reuse the handle_ix_list 
            # function and do not have to put a lot of special case code here...
            return walk(('structure-ix', handle_list_ix(('list', [sargs]), walk(ix)), rest))

    else: # not yet implemented
        raise ValueError("illegal index operation for {}".format(v[0]))

#########################################################################
def list_exp(node):

    (LIST, inlist) = node
    assert_match(LIST, ['list', 'raw-list'])

    outlist =[]

    for e in inlist:
        outlist.append(walk(e))

    return ('list', outlist)

#########################################################################
def escape_exp(node):

    (ESCAPE, s) = node
    assert_match(ESCAPE, 'escape')

    global __retval__
    __retval__ = ('none',)

    exec(s)

    return __retval__

#########################################################################
def is_exp(node):

    (IS, term, pattern) = node
    assert_match(IS, 'is')

    term_val = walk(term)
    
    try:
        unifiers = unify(term_val, pattern)
    except:
        return ('boolean', 'false')
    else:
        declare_unifiers(unifiers)
        return ('boolean', 'true')

#########################################################################
def in_exp(node):

    (IN, exp, exp_list) = node
    assert_match(IN, 'in')

    exp_val = walk(exp)
    (EXP_LIST_TYPE, exp_list_val, *_) = walk(exp_list)

    if EXP_LIST_TYPE not in ['list', 'raw-list']:
        raise ValueError("right argument to in operator has to be a list")

    # we simply map our in operator to the Python in operator
    if exp_val in exp_list_val:
        return ('boolean', 'true')
    else:
        return ('boolean', 'false')

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

    # the behavior is start and stop included
    if int(step_val) > 0: # generate the list
        ix = int(start_val)
        while ix <= int(stop_val):
            out_list_val.append(('integer', str(ix)))
            ix += int(step_val)

    elif int(step_val) == 0: # error
        raise ValueError("step size of 0 not supported")

    elif int(step_val) < 0: # generate the list
        ix = int(stop_val)
        while ix >= int(start_val):
            out_list_val.append(('integer', str(ix)))
            ix += int(step_val)

    return ('list', out_list_val)

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
        raise ValueError("walk: unknown tree node type: " + type)

# a dictionary to associate tree nodes with node functions
dispatch_dict = {
    # statements
    'attach'  : attach_stmt,
    'unify'   : unify_stmt,
    'get'     : get_stmt,
    'print'   : print_stmt,
    'callstmt': call_stmt,
    'return'  : return_stmt,
    'while'   : while_stmt,
    'if'      : if_stmt,
    'block'   : block_stmt,

    # expressions
    'list'    : list_exp,
    'raw-list' : list_exp,
    'to-list' : to_list_exp,
    'dict-access' : lambda node : node,
    'seq'     : lambda node : ('seq', walk(node[1]), walk(node[2])),
    'none'    : lambda node : node,
    'nil'     : lambda node : node,
    'function': lambda node : node, # looks like a constant
    'constructor' : lambda node : node, # looks like a constant
    'string'  : lambda node : node,
    'integer' : lambda node : node,
    'real'    : lambda node : node,
    'boolean' : lambda node : node,
    # type tag used in conjunction with escaped code in order to store
    # foreign constants in Asteroid data structures
    'foreign' : lambda node : node, 
    'id'      : lambda node : state.symbol_table.lookup_sym(node[1]),
    'apply'   : apply_exp,
    'structure-ix' : structure_ix_exp,
    'escape'  : escape_exp,
    'quote'   : lambda node : node[1],
    'is'      : is_exp,
    'in'      : in_exp,
}


