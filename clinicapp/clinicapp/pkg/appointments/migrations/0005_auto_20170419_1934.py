# -*- coding: utf-8 -*-
# Generated by Django 1.10.5 on 2017-04-19 19:34
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import django_extensions.db.fields


class Migration(migrations.Migration):
    dependencies = [
        ('clinics', '0005_diagnose_ignore_doctors'),
        ('appointments', '0004_auto_20170418_1328'),
    ]

    operations = [
        migrations.CreateModel(
            name='AppointmentRating',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name='ID')),
                ('created', django_extensions.db.fields.CreationDateTimeField(
                    auto_now_add=True, verbose_name='created')),
                ('modified',
                 django_extensions.db.fields.ModificationDateTimeField(
                     auto_now=True, verbose_name='modified')),
                ('rate', models.PositiveSmallIntegerField()),
                ('comment', models.CharField(max_length=1023)),
            ],
            options={
                'db_table': 'appointment_ratings',
            },
        ),
        migrations.AddField(
            model_name='appointment',
            name='clinic',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='appointments',
                to='clinics.Clinic'),
        ),
        migrations.AddField(
            model_name='appointmentrating',
            name='appointment',
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='rating', to='appointments.Appointment'),
        ),
    ]
