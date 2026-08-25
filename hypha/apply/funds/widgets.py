from django import forms
from django.utils import formats


class MultiCheckboxesWidget(forms.SelectMultiple):
    """
    Custom widget for Choices.js. Adds the required attributes.
    """

    def __init__(self, *args, **kwargs):
        attrs = kwargs.get("attrs", {})
        # Add the date attribute for Choices.js initialization
        attrs.setdefault("data-js-choices", "")
        attrs.setdefault("data-placeholder", "")
        kwargs["attrs"] = attrs
        super().__init__(*args, **kwargs)


class LocalizedCurrencyWidget(forms.NumberInput):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("attrs", {}).setdefault("min", 0)
        super().__init__(*args, **kwargs)

    def format_value(self, value):
        if not value or isinstance(value, str):
            return value
        return formats.number_format(value, use_l10n=True, force_grouping=True)
