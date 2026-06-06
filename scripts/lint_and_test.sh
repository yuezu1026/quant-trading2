#!/usr/bin/env bash
# Post-edit hook: lint + unit test
# 自动在代码修改后运行 lint 和单元测试
set -e
cd "$(dirname "$0")/.."

PYTHON="/c/Users/39002/AppData/Local/Programs/Python/Python312/python.exe"

echo "=============================================="
echo "  Post-Edit Hook: Lint & Test"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================="

# ------------------------------------------------------------------
# Step 1: Lint 检查 (ruff > compileall 语法检查)
# ------------------------------------------------------------------
echo ""
echo ">>> Step 1/3: 代码检查 (Lint)"

LINT_OK=true
if "$PYTHON" -m ruff --version &>/dev/null; then
    echo "[INFO] 使用 ruff 进行代码检查..."
    if "$PYTHON" -m ruff check . 2>&1; then
        echo "[PASS] ruff 检查通过"
    else
        echo "[FAIL] ruff 发现问题，请修复后重试"
        LINT_OK=false
    fi
else
    echo "[INFO] ruff 未安装，使用 compileall 语法检查..."
    if "$PYTHON" -m compileall -q . 2>&1; then
        echo "[PASS] 语法检查通过"
    else
        echo "[FAIL] 语法错误，请修复后重试"
        LINT_OK=false
    fi
fi

if [ "$LINT_OK" = false ]; then
    echo ""
    echo "=============================================="
    echo "  ❌ Lint 失败 — 请修复后重新保存文件"
    echo "=============================================="
    exit 2
fi

# ------------------------------------------------------------------
# Step 2: 单元测试
# ------------------------------------------------------------------
echo ""
echo ">>> Step 2/3: 单元测试"

TEST_OK=true
if "$PYTHON" -m pytest tests/ -v --tb=short -q 2>&1; then
    echo "[PASS] 单元测试全部通过"
else
    echo "[FAIL] 单元测试失败，请修复后重试"
    TEST_OK=false
fi

if [ "$TEST_OK" = false ]; then
    echo ""
    echo "=============================================="
    echo "  ❌ 测试失败 — 请修复后重新保存文件"
    echo "=============================================="
    exit 2
fi

# ------------------------------------------------------------------
# Step 3: 检查 TODO/FIXME
# ------------------------------------------------------------------
echo ""
echo ">>> Step 3/3: 代码规范检查"

# 检查最近修改的 Python 文件中是否有 TODO 或 FIXME
CHANGED_FILES=$(git diff --name-only HEAD 2>/dev/null | grep '\.py$' || true)
if [ -n "$CHANGED_FILES" ]; then
    TODO_COUNT=$(grep -n "TODO\|FIXME" $CHANGED_FILES 2>/dev/null | wc -l || echo 0)
    if [ "$TODO_COUNT" -gt 0 ]; then
        echo "[WARN] 发现 $TODO_COUNT 处 TODO/FIXME，请确认是否完成:"
        grep -n "TODO\|FIXME" $CHANGED_FILES 2>/dev/null || true
    else
        echo "[PASS] 未发现 TODO/FIXME"
    fi
else
    echo "[INFO] 无 Python 文件变更"
fi

echo ""
echo "=============================================="
echo "  ✅ Lint & Test 全部通过！"
echo "  请使用 git commit 提交代码到 GitHub"
echo "=============================================="
