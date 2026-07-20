# sql/extensions

> 内部二次开发扩展，**对上游零侵入**。
> 业务定制代码优先放这里。

## 目录约定

```
sql/extensions/
  <feature_name>/
    __init__.py
    apps.py
    models.py
    views.py
    serializers.py
    urls.py
    tasks.py
    services/
    tests/
    README.md   # 描述这个 feature 的设计
```

## 注册方式

1. 在 `sql/extensions/<feature>/apps.py` 中定义 `AppConfig`
2. 在 `archery/settings.py` 的 `INSTALLED_APPS` 加上 `"sql.extensions.<feature>.apps.<FeatureConfig>"`
3. 在 `archery/urls.py` 中 `include` URL

> 不需要往 `INSTALLED_APPS` 加也行，作为 `sql` 的子模块直接用。
