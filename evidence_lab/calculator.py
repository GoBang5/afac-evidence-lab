"""Bounded arithmetic over cited operands. Never evaluates Python code.

Units describe scale and a coarse dimension; currency identity and semantic
choice of operands still require model/human judgement.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from decimal import Decimal, localcontext
import re

UNITS = {
    'number': ('scalar', 1), 'ratio': ('scalar', 1), 'percent': ('scalar', '.01'),
    'money': ('money', 1), 'money_thousand': ('money', 1000),
    'money_million': ('money', 1000000), 'money_billion': ('money', 1000000000),
    'count': ('count', 1), 'count_thousand': ('count', 1000),
    'count_million': ('count', 1000000),
}
TOKEN = re.compile(r'(?<![\w.])\(?[-+−]?\$?\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?\s*%?(?!\w|\.\d)')


def number_token(text):
    value = text.strip().replace(',', '').replace('$', '').replace(' ', '').replace('−', '-').rstrip('%')
    if value.startswith('(') and value.endswith(')'):
        value = '-' + value[1:-1]
    result = Decimal(value)
    if not result.is_finite() or abs(result) > Decimal('1e24'):
        raise ValueError('operand_out_of_bounds')
    return result


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    dimension: str


def quantity(value, unit):
    if unit not in UNITS:
        raise ValueError('unknown_unit')
    dimension, scale = UNITS[unit]
    return Quantity(Decimal(str(value)) * Decimal(str(scale)), dimension)


def evaluate(expression, variables, output_unit):
    if not isinstance(expression, str) or len(expression) > 800:
        raise ValueError('invalid_expression')
    tree = ast.parse(expression, mode='eval')
    if len(list(ast.walk(tree))) > 100:
        raise ValueError('expression_too_complex')
    used = set()

    def visit(node):
        if isinstance(node, ast.Name) and node.id in variables:
            used.add(node.id)
            return variables[node.id]
        if isinstance(node, ast.Constant) and type(node.value) is int and 0 <= node.value <= 100:
            return quantity(node.value, 'number')
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            v = visit(node.operand)
            return Quantity(v.value if isinstance(node.op, ast.UAdd) else -v.value, v.dimension)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            a, b = visit(node.left), visit(node.comparators[0])
            if a.dimension != b.dimension:
                raise ValueError('incompatible_comparison_units')
            op = node.ops[0]
            if isinstance(op, ast.Gt): return a.value > b.value
            if isinstance(op, ast.Lt): return a.value < b.value
            if isinstance(op, ast.GtE): return a.value >= b.value
            if isinstance(op, ast.LtE): return a.value <= b.value
            if isinstance(op, ast.Eq): return a.value == b.value
            if isinstance(op, ast.NotEq): return a.value != b.value
            raise ValueError('unsupported_comparison')
        if not isinstance(node, ast.BinOp):
            raise ValueError('unsupported_expression')
        a, b = visit(node.left), visit(node.right)
        if isinstance(node.op, (ast.Add, ast.Sub)):
            if a.dimension != b.dimension:
                raise ValueError('incompatible_addition_units')
            return Quantity(a.value + b.value if isinstance(node.op, ast.Add) else a.value - b.value, a.dimension)
        if isinstance(node.op, ast.Mult):
            if a.dimension != 'scalar' and b.dimension != 'scalar':
                raise ValueError('unsupported_product_units')
            return Quantity(a.value * b.value, b.dimension if a.dimension == 'scalar' else a.dimension)
        if isinstance(node.op, ast.Div):
            if b.value == 0:
                raise ValueError('division_by_zero')
            if a.dimension != b.dimension and b.dimension != 'scalar':
                raise ValueError('incompatible_division_units')
            return Quantity(a.value / b.value, 'scalar' if a.dimension == b.dimension else a.dimension)
        if isinstance(node.op, ast.Pow):
            if a.dimension != 'scalar' or b.dimension != 'scalar' or abs(b.value) > 10 or a.value < 0:
                raise ValueError('unsupported_power')
            return Quantity(a.value ** b.value, 'scalar')
        raise ValueError('unsupported_operator')

    with localcontext() as ctx:
        ctx.prec = 32
        result = visit(tree.body)
        if not used or used != set(variables):
            raise ValueError('unused_or_missing_operands')
        if type(result) is bool:
            return result
        target = quantity(1, output_unit)
        if result.dimension != target.dimension:
            raise ValueError('output_unit_mismatch')
        answer = result.value / target.value
        if not answer.is_finite() or abs(answer) > Decimal('1e24'):
            raise ValueError('result_out_of_bounds')
        return float(answer)


def execute_plan(plan, evidence):
    rows = {r['fact_id']: r for r in evidence}
    operands = plan.get('operands')
    if not isinstance(operands, dict) or not 1 <= len(operands) <= 20:
        raise ValueError('missing_operands')
    variables, citations = {}, []
    for name, operand in operands.items():
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', name) or not isinstance(operand, dict):
            raise ValueError('invalid_operand')
        fact = operand.get('fact_id')
        if fact not in rows:
            raise ValueError('unknown_citation')
        token = operand.get('source_token')
        if not isinstance(token, str) or not token.strip():
            raise ValueError('missing_source_token')
        # Match a whole numerical token, never a substring of another amount.
        def canonical_token(s):
            return s.strip().replace('$', '').replace(' ', '').replace('−', '-')
        tokens = [canonical_token(m.group()) for m in TOKEN.finditer(rows[fact]['text'])]
        if canonical_token(token) not in tokens:
            raise ValueError('operand_not_in_cited_evidence')
        value = number_token(token)
        unit = operand.get('unit')
        if '%' in token and unit != 'percent':
            raise ValueError('percent_source_requires_percent_unit')
        variables[name] = quantity(value, unit)
        citations.append(fact)
    answer = evaluate(plan.get('expression'), variables, plan.get('output_unit'))
    return answer, sorted(set(citations))


def canonical_plan(plan):
    """Remove only an explicit final percentage display factor, not inner math.

Models commonly express percent as (a/b)*100. Convert that presentation to
ratio before unit execution to avoid applying the output scale twice.
"""
    if plan.get('output_unit') != 'percent':
        return plan
    expression = plan.get('expression')
    if not isinstance(expression, str) or len(expression) > 800:
        raise ValueError('invalid_expression')
    tree = ast.parse(expression, mode='eval').body
    if isinstance(tree, ast.BinOp) and isinstance(tree.op, ast.Mult):
        if isinstance(tree.right, ast.Constant) and tree.right.value == 100:
            expression = ast.get_source_segment(expression, tree.left)
        elif isinstance(tree.left, ast.Constant) and tree.left.value == 100:
            expression = ast.get_source_segment(expression, tree.right)
    return {**plan, 'output_unit': 'ratio', 'expression': expression,
            'original_output_unit': 'percent', 'original_expression': plan.get('expression')}
