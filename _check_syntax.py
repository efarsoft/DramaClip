import ast
import sys

try:
    with open('app/ipc/handlers.py', encoding='utf-8') as f:
        ast.parse(f.read())
    print('OK')
except SyntaxError as e:
    print(f'SYNTAX ERROR: {e}')
    sys.exit(1)
