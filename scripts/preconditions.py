"""Caller contracts shared by application functions; checks run before side effects.

Permissive parsers explicitly accept JSON values, including missing values.
No-argument functions retain their no-argument contract. Domain-specific checks
(e.g. evidence identity/date bounds) remain at the application boundary.
"""
import functools
import inspect
from annotationlib import Format
import math
import os
from collections.abc import Mapping, Iterable
from datetime import date, datetime


class PreconditionError(ValueError):
    """An argument does not satisfy the called function's input contract."""


def _accepts(rule, value, _seen=None):
    if not isinstance(rule, str) or not rule:
        raise PreconditionError('Precondition rule must be nonempty text')
    if rule.startswith('?'):
        return value is None or _accepts(rule[1:], value)
    if rule == 'mapping': return isinstance(value, Mapping)
    if rule == 'iterable': return isinstance(value, Iterable) and not isinstance(value,(str,bytes))
    if rule == 'sequence': return isinstance(value, (list, tuple))
    if rule == 'set': return isinstance(value, (set, frozenset))
    if rule == 'text': return isinstance(value, str)
    if rule == 'nonempty': return isinstance(value, str) and bool(value.strip())
    if rule == 'path': return isinstance(value, (str, os.PathLike)) and bool(os.fspath(value))
    if rule == 'bool': return isinstance(value, bool)
    if rule == 'int': return isinstance(value, int) and not isinstance(value, bool)
    if rule == 'positive_int': return _accepts('int',value) and value > 0
    if rule == 'nonnegative_int': return _accepts('int',value) and value >= 0
    if rule.startswith('enum:'): return isinstance(value,str) and value in rule[5:].split('|')
    if rule == 'number': return isinstance(value, (int,float)) and not isinstance(value,bool) and math.isfinite(value)
    if rule == 'positive': return _accepts('number',value) and value > 0
    if rule == 'nonnegative': return _accepts('number',value) and value >= 0
    if rule == 'datetime': return isinstance(value, datetime)
    if rule == 'date':
        try: return isinstance(value,str) and date.fromisoformat(value).isoformat() == value
        except ValueError: return False
    if rule == 'timestamp':
        try: return isinstance(value,str) and isinstance(datetime.fromisoformat(value.replace('Z','+00:00')),datetime)
        except ValueError: return False
    if rule == 'callable': return callable(value)
    if rule == 'entry': return isinstance(getattr(value,'columns',None), Mapping)
    if rule == 'candidate': return all(hasattr(value,k) for k in ('model_name','benchmark'))
    if rule == 'response': return hasattr(value,'status_code') and callable(getattr(value,'json',None))
    if rule == 'page': return callable(getattr(value,'query_selector_all',None)) or callable(getattr(value,'locator',None))
    if rule == 'content_page': return callable(getattr(value,'content',None))
    if rule == 'namespace': return hasattr(value,'__dict__')
    if rule == 'json':
        if value is None or isinstance(value,(str,bool,int)): return True
        if isinstance(value,float): return math.isfinite(value)
        if not isinstance(value,(list,tuple,dict)): return False
        seen = set() if _seen is None else _seen
        identity = id(value)
        if identity in seen: return False
        seen.add(identity)
        try:
            if isinstance(value,dict):
                return all(isinstance(k,str) and _accepts('json',v,seen) for k,v in value.items())
            return all(_accepts('json',v,seen) for v in value)
        finally:
            seen.remove(identity)
    raise ValueError('Unknown precondition rule: '+rule)


def preconditions(**rules):
    """Declare argument contracts, preserving function metadata and signatures."""
    def decorate(function):
        signature=inspect.signature(function, annotation_format=Format.STRING)
        unknown=set(rules)-set(signature.parameters)
        if unknown: raise TypeError(f'{function.__qualname__}: unknown contract arguments {unknown}')
        positional = [p.name for p in signature.parameters.values()
                      if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        required = sum(p.default is inspect.Parameter.empty for p in signature.parameters.values()
                       if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))
        keyword_required = any(p.kind is p.KEYWORD_ONLY and p.default is inspect.Parameter.empty
                               for p in signature.parameters.values())
        positions = {name: i for i, name in enumerate(positional)}
        fast_rules = [(positions[name], name, rule) for name, rule in rules.items() if name in positions]
        def check(*args,**kwargs):
            if not kwargs and not keyword_required and required <= len(args) <= len(positional):
                # Tight numeric/name parsing loops should not repeatedly build BoundArguments.
                for i, name, rule in fast_rules:
                    value = args[i] if i < len(args) else signature.parameters[name].default
                    if not _accepts(rule,value):
                        raise PreconditionError(f'{function.__qualname__}: {name} must satisfy {rule}')
                for name, rule in rules.items():
                    if name not in positions and not _accepts(rule,signature.parameters[name].default):
                        raise PreconditionError(f'{function.__qualname__}: {name} must satisfy {rule}')
                return
            bound=signature.bind(*args,**kwargs)
            bound.apply_defaults()
            for name,rule in rules.items():
                if not _accepts(rule,bound.arguments[name]):
                    raise PreconditionError(f'{function.__qualname__}: {name} must satisfy {rule}')
        @functools.wraps(function, assigned=tuple(a for a in functools.WRAPPER_ASSIGNMENTS if a != "__annotations__"))
        def guarded(*args,**kwargs):
            check(*args,**kwargs)
            return function(*args,**kwargs)
        guarded.__signature__=signature
        guarded.check_preconditions=check
        guarded.precondition_rules=rules
        return guarded
    return decorate
