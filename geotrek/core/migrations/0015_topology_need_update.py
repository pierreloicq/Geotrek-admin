# -*- coding: utf-8 -*-
# Generated by Django 1.11.14 on 2020-04-01 10:36
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_auto_20200228_1755'),
    ]

    operations = [
        migrations.AddField(
            model_name='topology',
            name='need_update',
            field=models.BooleanField(default=False),
        ),
    ]