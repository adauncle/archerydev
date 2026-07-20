"""Migrations 包占位。

首次接入本 app 时，在项目根目录执行：

    python manage.py makemigrations dingtalk_oa

Django 会自动生成 ``0001_initial.py`` 包含本 app 所有模型的建表语句。
然后再 ``python manage.py migrate`` 即可。

**不要**手动创建 ``0001_initial.py`` —— 手动写出来的与
``makemigrations`` 生成的会冲突，导致重复建表。
"""
