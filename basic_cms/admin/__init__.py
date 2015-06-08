# -*- coding: utf-8 -*-
"""Page Admin module."""
from basic_cms import settings
from basic_cms.models import Page, Content, PageAlias
from basic_cms.http import get_language_from_request, get_template_from_request
from basic_cms.utils import get_placeholders
from basic_cms.templatetags.pages_tags import PlaceholderNode
from basic_cms.admin.utils import get_connected, make_inline_admin
from basic_cms.admin.forms import make_form
from basic_cms.admin.views import traduction, get_content, sub_menu
from basic_cms.admin.views import change_status, modify_content, delete_content
from basic_cms.admin.views import move_page
from basic_cms.admin.actions import export_pages_as_json, import_pages_from_json

from django import forms
from django.contrib import admin
from django.utils.translation import ugettext_lazy as _
from django.utils.encoding import force_text
from django.conf import settings as global_settings
from django.http import Http404
from django.contrib.admin.sites import AlreadyRegistered
if global_settings.USE_I18N:
    from django.views.i18n import javascript_catalog
else:
    from django.views.i18n import null_javascript_catalog as javascript_catalog

from os.path import join


class PageAdmin(admin.ModelAdmin):
    """Page Admin class."""

    exclude = ['author', 'parent']
    # these mandatory fields are not versioned
    mandatory_placeholders = ('title', 'slug')
    general_fields = ['title', 'slug', 'status', 'target',
        'position', 'freeze_date']

    if settings.PAGE_USE_SITE_ID and not settings.PAGE_HIDE_SITES:
        general_fields.append('sites')
    insert_point = general_fields.index('status') + 1

    # Strange django behavior. If not provided, django will try to find
    # 'page' foreign key in all registered models
    inlines = []

    general_fields.insert(insert_point, 'tags')

    # Add support for future dating and expiration based on settings.
    if settings.PAGE_SHOW_END_DATE:
        general_fields.insert(insert_point, 'publication_end_date')
    if settings.PAGE_SHOW_START_DATE:
        general_fields.insert(insert_point, 'publication_date')

    from basic_cms.urlconf_registry import registry
    if(len(registry)):
        general_fields.append('delegate_to')
        insert_point = general_fields.index('status') + 1

    normal_fields = ['language']
    page_templates = settings.get_page_templates()
    if len(page_templates) > 0:
        normal_fields.append('template')
    normal_fields.append('redirect_to')
    normal_fields.append('redirect_to_url')
    fieldsets = (
        [_('General'), {
            'fields': general_fields,
            'classes': ('module-general',),
        }],
        (_('Options'), {
            'fields': normal_fields,
            'classes': ('module-options',),
        }),
    )

    actions = [export_pages_as_json]

    metadata_fields = [
        {'name': 'meta_title',
        'field': forms.fields.CharField(required=False)},
        {'name': 'meta_description',
        'field': forms.fields.CharField(required=False, widget=forms.widgets.Textarea()), },
        {'name': 'meta_keywords',
        'field': forms.fields.CharField(required=False, widget=forms.widgets.Textarea()), },
        {'name': 'meta_author',
        'field': forms.fields.CharField(required=False), },
        {'name': 'fb_page_type',
        'field': forms.fields.CharField(required=False), },
        {'name': 'fb_image',
        'field': forms.fields.CharField(required=False), },
    ]

    class Media:
        css = {
            'all': [join(settings.PAGES_MEDIA_URL, path) for path in (
                'css/rte.css',
                'css/pages.css'
            )]
        }
        js = [join(settings.PAGES_MEDIA_URL, path) for path in (
            'javascript/jquery.js',
            'javascript/jquery.rte.js',
            'javascript/pages.js',
            'javascript/pages_list.js',
            'javascript/pages_form.js',
            'javascript/jquery.query-2.1.7.js',
        )]

    def urls(self):
        from django.conf.urls import patterns, url

        # Admin-site-wide views.
        urlpatterns = patterns('',
            url(r'^$', self.list_pages, name='page-index'),
            url(r'^(?P<page_id>[0-9]+)/traduction/(?P<language_id>[-\w]+)/$',
                traduction, name='page-traduction'),
            url(r'^(?P<page_id>[0-9]+)/get-content/(?P<content_id>[0-9]+)/$',
                get_content, name='page-get-content'),
            url(r'^(?P<page_id>[0-9]+)/modify-content/(?P<content_type>[-\w]+)/(?P<language_id>[-\w]+)/$',
                modify_content, name='page-modify-content'),
            url(r'^(?P<page_id>[0-9]+)/delete-content/(?P<language_id>[-\w]+)/$',
                delete_content, name='page-delete-content'),
            url(r'^(?P<page_id>[0-9]+)/sub-menu/$',
                sub_menu, name='page-sub-menu'),
            url(r'^(?P<page_id>[0-9]+)/move-page/$',
                move_page, name='page-move-page'),
            url(r'^(?P<page_id>[0-9]+)/change-status/$',
                change_status, name='page-change-status'),
            url(r'^import-json/$',
                self.import_pages, name='import-pages-from-json'),
        )
        urlpatterns += super(PageAdmin, self).urls

        return urlpatterns

    urls = property(urls)

    def i18n_javascript(self, request):
        """Displays the i18n JavaScript that the Django admin
        requires.

        This takes into account the ``USE_I18N`` setting. If it's set to False, the
        generated JavaScript will be leaner and faster.
        """
        return javascript_catalog(request, packages='pages')

    def save_model(self, request, page, form, change):
        """Move the page in the tree if necessary and save every
        placeholder :class:`Content <pages.models.Content>`.
        """
        language = form.cleaned_data['language']
        target = form.data.get('target', None)
        position = form.data.get('position', None)
        page.save()

        # if True, we need to move the page
        if target and position:
            try:
                target = self.model.objects.get(pk=target)
            except self.model.DoesNotExist:
                pass
            else:
                target.invalidate()
                page.move_to(target, position)

        for name in self.mandatory_placeholders:
            data = form.cleaned_data[name]
            placeholder = PlaceholderNode(name)
            extra_data = placeholder.get_extra_data(form.data)
            placeholder.save(page, language, data, change,
                extra_data=extra_data)

        for placeholder in get_placeholders(page.get_template()):
            if(placeholder.name in form.cleaned_data and placeholder.name
                    not in self.mandatory_placeholders):
                data = form.cleaned_data[placeholder.name]
                extra_data = placeholder.get_extra_data(form.data)
                placeholder.save(page, language, data, change,
                    extra_data=extra_data)

        for placeholder in self.metadata_fields:
            data = form.cleaned_data[placeholder['name']]
            Content.objects.set_or_create_content(
                    page,
                    language,
                    placeholder['name'],
                    data
            )

        page.invalidate()

    def get_fieldsets(self, request, obj=None):
        """
        Add fieldsets of placeholders to the list of already
        existing fieldsets.
        """

        # some ugly business to remove freeze_date
        # from the field list
        general_module = {
            'fields': list(self.general_fields),
            'classes': ('module-general',),
        }

        default_fieldsets = list(self.fieldsets)
        if not request.user.has_perm('pages.can_freeze'):
            general_module['fields'].remove('freeze_date')
        if not request.user.has_perm('pages.can_publish'):
            general_module['fields'].remove('status')

        default_fieldsets[0][1] = general_module

        placeholder_fieldsets = []
        template = get_template_from_request(request, obj)
        for placeholder in get_placeholders(template):
            if placeholder.name not in self.mandatory_placeholders:
                placeholder_fieldsets.append(placeholder.name)

        additional_fieldsets = []

        # meta fields
        metadata_fieldsets = [f['name'] for f in self.metadata_fields]
        additional_fieldsets.append((_('Metadata'), {
            'fields': metadata_fieldsets,
            'classes': ('module-content', 'grp-collapse grp-closed'),
        }))
        additional_fieldsets.append((_('Content'), {
            'fields': placeholder_fieldsets,
            'classes': ('module-content',),
        }))

        return default_fieldsets + additional_fieldsets

    def save_form(self, request, form, change):
        """Given a ModelForm return an unsaved instance. ``change`` is True if
        the object is being changed, and False if it's being added."""
        instance = super(PageAdmin, self).save_form(request, form, change)
        instance.template = form.cleaned_data['template']
        if not change:
            instance.author = request.user
        return instance

    def get_form(self, request, obj=None, **kwargs):
        """Get a :class:`Page <pages.admin.forms.PageForm>` for the
        :class:`Page <pages.models.Page>` and modify its fields depending on
        the request."""
        #form = super(PageAdmin, self).get_form(request, obj, **kwargs)
        template = get_template_from_request(request, obj)
        form = make_form(self.model, get_placeholders(template))

        language = get_language_from_request(request)
        form.base_fields['language'].initial = language
        if obj:
            initial_slug = obj.slug(language=language, fallback=False)
            initial_title = obj.title(language=language, fallback=False)
            form.base_fields['slug'].initial = initial_slug
            form.base_fields['title'].initial = initial_title
            form.base_fields['slug'].label = _('Slug')

        template = get_template_from_request(request, obj)
        page_templates = settings.get_page_templates()
        if len(page_templates) > 0:
            template_choices = list(page_templates)
            template_choices.insert(0, (settings.PAGE_DEFAULT_TEMPLATE,
                    _('Default template')))
            form.base_fields['template'].choices = template_choices
            form.base_fields['template'].initial = force_text(template)

        for placeholder in get_placeholders(template):
            name = placeholder.name
            if obj:
                initial = placeholder.get_content(obj, language, name)
            else:
                initial = None
            form.base_fields[name] = placeholder.get_field(obj,
                language, initial=initial)

        for placeholder in self.metadata_fields:
            name = placeholder['name']
            initial = None
            if obj:
                try:
                    initial = Content.objects.get(page=obj, language=language, type=name).body
                except Content.DoesNotExist:
                    pass
            form.base_fields[name] = placeholder['field']
            form.base_fields[name].initial = initial

        return form

    def change_view(self, request, object_id, extra_context=None):
        """The ``change`` admin view for the
        :class:`Page <pages.models.Page>`."""
        language = get_language_from_request(request)
        extra_context = {
            'language': language,
            # don't see where it's used
            #'lang': current_lang,
            'page_languages': settings.PAGE_LANGUAGES,
        }
        try:
            int(object_id)
        except ValueError:
            raise Http404('The "%s" part of the location is invalid.'
                % str(object_id))
        try:
            obj = self.model.objects.get(pk=object_id)
        except self.model.DoesNotExist:
            # Don't raise Http404 just yet, because we haven't checked
            # permissions yet. We don't want an unauthenticated user to be able
            # to determine whether a given object exists.
            obj = None
        else:
            template = get_template_from_request(request, obj)
            extra_context['placeholders'] = get_placeholders(template)
            extra_context['traduction_languages'] = [l for l in
                settings.PAGE_LANGUAGES if Content.objects.get_content(obj,
                                    l[0], "title") and l[0] != language]
        extra_context['page'] = obj
        return super(PageAdmin, self).change_view(request, object_id,
                                                        extra_context=extra_context)

    def add_view(self, request, form_url='', extra_context=None):
        """The ``add`` admin view for the :class:`Page <pages.models.Page>`."""
        extra_context = {
            'language': get_language_from_request(request),
            'page_languages': settings.PAGE_LANGUAGES,
        }
        return super(PageAdmin, self).add_view(request, form_url,
                                                            extra_context)

    def has_add_permission(self, request):
        """Return ``True`` if the current user has permission to add a new
        page."""
        return request.user.has_perm('pages.add_page')

    def has_change_permission(self, request, obj=None):
        """Return ``True`` if the current user has permission
        to change the page."""
        return request.user.has_perm('pages.change_page')

    def has_delete_permission(self, request, obj=None):
        """Return ``True`` if the current user has permission on the page."""
        return request.user.has_perm('pages.delete_page')

    def list_pages(self, request, template_name=None, extra_context=None):
        """List root pages"""
        if not self.admin_site.has_permission(request):
            return self.admin_site.login(request)
        language = get_language_from_request(request)

        query = request.POST.get('q', '').strip()

        if query:
            page_ids = list(set([c.page.pk for c in
                Content.objects.filter(body__icontains=query)]))
            pages = Page.objects.filter(pk__in=page_ids)
        else:
            pages = Page.objects.root()
        if settings.PAGE_HIDE_SITES:
            pages = pages.filter(sites=settings.SITE_ID)

        context = {
            'can_publish': request.user.has_perm('pages.can_publish'),
            'language': language,
            'name': _("page"),
            'pages': pages,
            'opts': self.model._meta,
            'q': query
        }

        context.update(extra_context or {})
        change_list = self.changelist_view(request, context)

        return change_list

    def import_pages(self, request):
        if not self.has_add_permission(request):
            return admin.site.login(request)

        return import_pages_from_json(request)


class PageAdminWithDefaultContent(PageAdmin):
    """
    Fill in values for content blocks from official language
    if creating a new translation
    """
    def get_form(self, request, obj=None, **kwargs):
        form = super(PageAdminWithDefaultContent, self
            ).get_form(request, obj, **kwargs)

        language = get_language_from_request(request)

        if global_settings.LANGUAGE_CODE == language:
            # this is the "official" language
            return form

        if Content.objects.filter(page=obj, language=language).count():
            return form

        # this is a new page, try to find some default content
        template = get_template_from_request(request, obj)
        for placeholder in get_placeholders(template):
            name = placeholder.name
            form.base_fields[name] = placeholder.get_field(obj, language,
                initial=Content.objects.get_content(obj,
                    global_settings.LANGUAGE_CODE, name))
        return form


for admin_class, model, options in get_connected():
    PageAdmin.inlines.append(make_inline_admin(admin_class, model, options))

try:
    admin.site.register(Page, PageAdmin)
except AlreadyRegistered:
    pass


class ContentAdmin(admin.ModelAdmin):
    list_display = ('__unicode__', 'type', 'language', 'page')
    list_filter = ('page',)
    search_fields = ('body',)


class AliasAdmin(admin.ModelAdmin):
    list_display = ('page', 'url',)
    list_editable = ('url',)

try:
    admin.site.register(PageAlias, AliasAdmin)
except AlreadyRegistered:
    pass
