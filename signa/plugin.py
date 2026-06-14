import os

from app.plugins import PluginBase, Menu, MountPoint
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils.translation import gettext as _, gettext_lazy as _l
from django import forms

from .api import TaskFindGCPDetect, TaskFindGCPCheck, FindGCPSettings, read_user_defaults
from .params import DICT_CHOICES, validate_marker_params


# Field labels/help_texts are evaluated at class-definition (module import)
# time, so they must be lazy — plain gettext would freeze them in whatever
# language was active when the module loaded.
class FindGCPSettingsForm(forms.Form):
    epsg = forms.IntegerField(label=_l("EPSG (target CRS)"), min_value=1024, max_value=999999)
    dict_id = forms.ChoiceField(label=_l("ArUco dictionary"), choices=DICT_CHOICES)
    minrate = forms.FloatField(
        label=_l("minrate"), min_value=0.005, max_value=1.0,
        help_text=_l("Minimum relative marker size. Lower it step by step (0.01 → 0.008 → 0.005) if markers are missed — never below 0.005. Markers should be at least 20×20 px in the image."))
    ignore = forms.FloatField(
        label=_l("ignore"), min_value=0.0, max_value=0.99,
        help_text=_l("Ignored margin per marker cell, compensates overexposed (burnt-in) marker borders. 0.13 (OpenCV default) up to 0.33 in strong sunlight."))
    adjust = forms.BooleanField(label=_l("Color adjustment (recommended for strong sunlight)"),
                                required=False)


class Plugin(PluginBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # WebODM has no official plugin-translation support: LOCALE_PATHS only
        # contains WebODM's own locale dir, and plugins are not Django apps. We
        # ship our own catalogs (locale/de/LC_MESSAGES/django.mo) and hook our
        # locale dir into LOCALE_PATHS here, in __init__ — NOT in register():
        # boot() is guarded by a shared-memory flag (webodm.wsgi.booted), so
        # register() runs in only ONE gunicorn worker, which made the language
        # flap per request (German only when the boot worker answered). The
        # plugin is instantiated in EVERY worker (get_plugins() runs on each
        # page render via the plugin template tags), so this hook is
        # per-worker-reliable. Idempotent via the membership check.
        locale_dir = self.get_path("locale")
        if os.path.isdir(locale_dir) and locale_dir not in settings.LOCALE_PATHS:
            settings.LOCALE_PATHS = list(settings.LOCALE_PATHS) + [locale_dir]
            # Drop per-language catalog caches so already-built languages are
            # rebuilt with our catalog merged in; re-activate the current
            # language so even the in-flight request switches over.
            from django.utils import translation
            from django.utils.translation import trans_real
            lang = translation.get_language()
            trans_real._translations = {}
            trans_real._default = None
            if lang:
                translation.activate(lang)

    def main_menu(self):
        return [
            Menu(_("Signa"), self.public_url(""), "fa fa-map-marker-alt fa-fw"),
            Menu(_("Signa Settings"), self.public_url("settings"), "fa fa-cog fa-fw"),
        ]

    def include_js_files(self):
        # Loaded into the dashboard; registers the "Signa task" button that
        # runs the single-pass workflow (see public/load_buttons.js). The
        # manifest version doubles as a cache-buster so browsers re-fetch the
        # script after every plugin update.
        version = self.get_manifest().get('version', '0')
        return ['load_buttons.js?v={}'.format(version)]

    def app_mount_points(self):
        @login_required
        def index(request):
            return render(request, self.template_path("app.html"), {
                'title': 'Signa',
                'defaults': read_user_defaults(self.get_user_data_store(request.user)),
                'dict_choices': DICT_CHOICES,
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
                    messages.success(request, _("Signa default settings saved."))
                else:
                    # The marker-print section needs its context here too,
                    # or its dictionary dropdown renders empty after a failed
                    # validation of the defaults form.
                    return render(request, self.template_path("settings.html"),
                                  {'title': 'Signa Settings', 'form': form,
                                   'dict_choices': DICT_CHOICES,
                                   'defaults': read_user_defaults(ds)})

            d = read_user_defaults(ds)
            form = FindGCPSettingsForm(initial={
                'epsg': d['epsg'], 'dict_id': str(d['dict']),
                'minrate': d['minrate'], 'ignore': d['ignore'], 'adjust': d['adjust'],
            })
            return render(request, self.template_path("settings.html"),
                          {'title': 'Signa Settings', 'form': form,
                           'dict_choices': DICT_CHOICES, 'defaults': d})

        @login_required
        def marker_pdf_view(request):
            # Plain form POST from the settings page; the response is the PDF
            # itself (the browser downloads it and stays on the settings page).
            # Errors go through the messages framework + redirect instead.
            if request.method != 'POST':
                return redirect(self.public_url("settings"))
            params, error = validate_marker_params(request.POST)
            if error is None:
                # Imported lazily: pulls in cv2, which only the enabled plugin's
                # site-packages guarantees — don't pay/risk that at module load.
                from .marker_pdf import build_marker_pdf
                pdf, error = build_marker_pdf(**params)
            if error is not None:
                # params/marker_pdf are Django-free and return plain English
                # strings; the runtime gettext lookup translates them.
                messages.error(request, _(error))
                return redirect(self.public_url("settings"))

            filename = 'aruco-markers-dict{}-id{}-{}-{}{}-{}.pdf'.format(
                params['dict_id'], params['id_from'], params['id_to'],
                params['page'], '-gray' if params['gray'] else '', params['aid'])
            response = HttpResponse(pdf, content_type='application/pdf')
            response['Content-Disposition'] = 'attachment; filename="{}"'.format(filename)
            return response

        return [
            MountPoint('$', index),
            MountPoint('settings$', settings_view),
            MountPoint('markers/pdf$', marker_pdf_view),
        ]

    def api_mount_points(self):
        return [
            MountPoint('task/(?P<pk>[^/.]+)/detect', TaskFindGCPDetect.as_view()),
            MountPoint('task/(?P<pk>[^/.]+)/check/(?P<celery_task_id>.+)', TaskFindGCPCheck.as_view()),
            MountPoint('settings$', FindGCPSettings.as_view()),
        ]
