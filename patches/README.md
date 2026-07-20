# Patches 目录

> 仅当你选择 **patch 模式** 时使用（不直接 fork，而是维护一个 diff 集合）。

## 用法

```bash
# 应用所有 patch
for p in patches/*.patch; do git apply "$p"; done

# 重新生成 patch（在合入上游代码的临时仓库）
git diff > patches/01_my-custom-change.patch
```

## 命名

`NN_<short-name>.patch`，NN 是顺序号（应用时按字典序）。
