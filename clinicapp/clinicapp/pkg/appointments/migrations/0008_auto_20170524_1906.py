# -*- coding: utf-8 -*-
# Generated by Django 1.11 on 2017-05-24 19:06
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('appointments', '0007_auto_20170517_1325'),
    ]

    operations = [
        migrations.AlterField(
            model_name='appointment',
            name='status',
            field=models.PositiveIntegerField(
                choices=[(10, 'Opened'), (20, 'WaitingForUserDecide'),
                         (30, 'UserRejectSuggestions'), (40, 'Reserved'),
                         (50, 'TimeOut'), (60, 'Confirmed'), (70, 'Canceled')],
                default=10),
        ),
    ]