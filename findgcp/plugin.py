from app.plugins import PluginBase, Menu, MountPoint
from django.shortcuts import render
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils.translation import gettext as _
from django import forms

from .api import TaskFindGCPDetect, TaskFindGCPCheck, FindGCPSettings, read_user_defaults


class FindGCPSettingsForm(forms.Form):
    epsg = forms.IntegerField(label=_("EPSG (target CRS)"), min_value=1024, max_value=999999)
    dict_id = forms.ChoiceField(label=_("ArUco dictionary"),
                                choices=[("1", "1 — DICT_4X4_100"), ("99", "99 — custom 3×3")])
    minrate = forms.FloatField(label=_("minrate"), min_value=0.0001, max_value=1.0)
    ignore = forms.FloatField(label=_("ignore"), min_value=0.0, max_value=0.99)
    adjust = forms.BooleanField(label=_("Color adjustment (recommended for strong sunlight)"),
                                required=False)


class Plugin(PluginBase):
    def main_menu(self):
        return [
            Menu(_("Find-GCP"), self.public_url(""), "fa fa-map-marker-alt fa-fw"),
            Menu(_("Find-GCP Settings"), self.public_url("settings"), "fa fa-cog fa-fw"),
        ]

    def include_js_files(self):
        # Loaded into the dashboard; registers the "Find-GCP task" button that
        # runs the single-pass workflow (see public/load_buttons.js).
        return ['load_buttons.js']

    def app_mount_points(self):
        @login_required
        def index(request):
            return render(request, self.template_path("app.html"), {
                'title': 'Find-GCP',
                'defaults': read_user_defaults(self.get_user_data_store(request.user)),
            })

        @login_required
        def settings_view(request):
            ds = self.get_user_data_store(request.user)
            if request.method == 'POST':
                form = FindGCPSettingsForm(request.POST)
                if form.is_valid():
                    cd = form.cleaned_data
                    ds.set_int('default_epsg', cd['epsg'])
                    ds.set_int('default_dict', int(cd['dict_id']))
                    ds.set_float('default_minrate', cd['minrate'])
                    ds.set_float('default_ignore', cd['ignore'])
                    ds.set_bool('default_adjust', cd['adjust'])
                    messages.success(request, _("Find-GCP default settings saved."))
                else:
                    return render(request, self.template_path("settings.html"),
                                  {'title': 'Find-GCP Settings', 'form': form})

            d = read_user_defaults(ds)
            form = FindGCPSettingsForm(initial={
                'epsg': d['epsg'], 'dict_id': str(d['dict']),
                'minrate': d['minrate'], 'ignore': d['ignore'], 'adjust': d['adjust'],
            })
            return render(request, self.template_path("settings.html"),
                          {'title': 'Find-GCP Settings', 'form': form})

        return [
            MountPoint('$', index),
            MountPoint('settings$', settings_view),
        ]

    def api_mount_points(self):
        return [
            MountPoint('task/(?P<pk>[^/.]+)/detect', TaskFindGCPDetect.as_view()),
            MountPoint('task/(?P<pk>[^/.]+)/check/(?P<celery_task_id>.+)', TaskFindGCPCheck.as_view()),
            MountPoint('settings$', FindGCPSettings.as_view()),
        ]
