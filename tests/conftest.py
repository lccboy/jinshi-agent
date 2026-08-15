# 项目根 conftest：把项目根加入 sys.path，保证 `import services...` 可用
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
