"""Tanzania's regions and their councils (LGAs), for a shop's Region and
Council dropdowns. Served to the app by GET /api/core/locations/, with the
countries, and used to check that a shop's council belongs to its region."""

from .countries import COUNTRIES, TANZANIA

REGIONS = {
    'Arusha Region': [
        'Monduli District Council', 'Meru District Council', 'Arusha City Council', 'Karatu District Council',
        'Longido District Council', 'Ngorongoro District Council', 'Arusha District Council',
    ],
    'Dar Es Salaam Region': [
        'Kinondoni Municipal Council', 'Ubungo Municipal Council', 'Ilala Municipal Council',
        'Kigamboni Municipal Council', 'Temeke Municipal Council',
    ],
    'Dodoma Region': [
        'Kondoa District Council', 'Kondoa Town Council', 'Mpwapwa District Council', 'Kongwa District Council',
        'Chamwino District Council', 'Dodoma Municipal Council', 'Bahi District Council', 'Chemba District Council',
    ],
    'Geita Region': [
        'Geita District Council', 'Geita Town Council', "Nyang'hwale District Council", 'Mbogwe District Council',
        'Bukombe District Council', 'Chato District Council',
    ],
    'Iringa Region': [
        'Iringa District Council', 'Mufindi District Council', 'Iringa Municipal Council',
        'Kilolo District Council', 'Mafinga Town Council',
    ],
    'Kagera Region': [
        'Karagwe District Council', 'Bukoba District Council', 'Muleba District Council',
        'Biharamulo District Council', 'Ngara District Council', 'Bukoba Municipal Council',
        'Missenyi District Council', 'Kyerwa District Council',
    ],
    'Katavi Region': [
        'Mpimbwe District Council', 'Mlele District Council', 'Tanganyika District Council',
        'Mpanda Municipal Council', 'Nsimbo District Council',
    ],
    'Kigoma Region': [
        'Kasulu District Council', 'Kibondo District Council', 'Kigoma District Council',
        'Kigoma Municipal Council', 'Uvinza District Council', 'Buhigwe District Council',
        'Kakonko District Council', 'Kasulu Town Council',
    ],
    'Kilimanjaro Region': [
        'Rombo District Council', 'Moshi District Council', 'Moshi Municipal Council', 'Mwanga District Council',
        'Same District Council', 'Hai District Council', 'Siha District Council',
    ],
    'Lindi Region': [
        'Kilwa District Council', 'Lindi Municipal Council', 'Mtama District Council',
        'Nachingwea District Council', 'Liwale District Council', 'Ruangwa District Council',
    ],
    'Manyara Region': [
        'Kiteto District Council', 'Babati District Council', 'Hanang District Council', 'Babati Town Council',
        'Mbulu Town Council', 'Mbulu District Council', 'Simanjiro District Council',
    ],
    'Mara Region': [
        'Tarime District Council', 'Tarime Town Council', 'Serengeti District Council',
        'Musoma District Council', 'Bunda District Council', 'Musoma Municipal Council',
        'Rorya District Council', 'Butiama District Council', 'Bunda Town Council',
    ],
    'Mbeya Region': [
        'Kyela District Council', 'Mbeya City Council', 'Chunya District Council', 'Mbeya District Council',
        'Mbarali District Council', 'Rungwe District Council', 'Busokelo District Council',
    ],
    'Songwe Region': [
        'Mbozi District Council', 'Songwe District Council', 'Ileje District Council', 'Momba District Council',
        'Tunduma Town Council',
    ],
    'Morogoro Region': [
        'Kilosa District Council', 'Morogoro District Council', 'Ifakara Town Council',
        'Mlimba District Council', 'Ulanga District Council', 'Malinyi District Council',
        'Morogoro Municipal Council', 'Mvomero District Council', 'Gairo District Council',
    ],
    'Mtwara Region': [
        'Mtwara District Council', 'Newala Town Council', 'Nanyamba Town Council', 'Nanyumbu District Council',
        'Newala District Council', 'Masasi District Council', 'Tandahimba District Council',
        'Mtwara Municipal Council', 'Masasi Town Council',
    ],
    'Mwanza Region': [
        'Sengerema District Council', 'Ukerewe District Council', 'Magu District Council',
        'Nyamagana Municipal Council', 'Kwimba District Council', 'Buchosa District Council',
        'Ilemela Municipal Council', 'Misungwi District Council',
    ],
    'Njombe Region': [
        'Njombe Town Council', "Wanging'ombe District Council", 'Makete District Council',
        'Njombe District Council', 'Ludewa District Council', 'Makambako Town Council',
    ],
    'Pwani Region': [
        'Chalinze District Council', 'Bagamoyo District Council', 'Kisarawe District Council',
        'Mkuranga District Council', 'Kibaha District Council', 'Rufiji District Council',
        'Kibiti District Council', 'Mafia District Council', 'Kibaha Town Council',
    ],
    'Rukwa Region': [
        'Kalambo District Council', 'Sumbawanga District Council', 'Nkasi District Council',
        'Sumbawanga Municipal Council',
    ],
    'Ruvuma Region': [
        'Songea Municipal Council', 'Tunduru District Council', 'Songea District Council',
        'Madaba District Council', 'Mbinga Town Council', 'Mbinga District Council',
        'Namtumbo District Council', 'Nyasa District Council',
    ],
    'Shinyanga Region': [
        'Shinyanga District Council', 'Kahama Town Council', 'Shinyanga Municipal Council',
        'Kishapu District Council', 'Msalala District Council', 'Ushetu District Council',
    ],
    'Simiyu Region': [
        'Bariadi District Council', 'Bariadi Town Council', 'Itilima District Council', 'Meatu District Council',
        'Maswa District Council', 'Busega District Council',
    ],
    'Singida Region': [
        'Manyoni District Council', 'Iramba District Council', 'Singida District Council',
        'Itigi District Council', 'Ikungi District Council', 'Singida Municipal Council',
        'Mkalama District Council',
    ],
    'Tabora Region': [
        'Nzega Town Council', 'Nzega District Council', 'Igunga District Council', 'Uyui District Council',
        'Urambo District Council', 'Sikonge District Council', 'Tabora Municipal Council',
        'Kaliua District Council',
    ],
    'Tanga Region': [
        'Muheza District Council', 'Lushoto District Council', 'Bumbuli District Council',
        'Korogwe District Council', 'Pangani District Council', 'Kilindi District Council',
        'Tanga City Council', 'Handeni District Council', 'Korogwe Town Council', 'Mkinga District Council',
        'Handeni Town Council',
    ],
}


def check_location(attrs, instance=None):
    """Errors ({field: message}) if the country isn't one of COUNTRIES or,
    in Tanzania, the region isn't one of REGIONS or the council isn't one
    of its councils; other countries' region and council are free text.
    A value left as it was is accepted, so a shop typed in before the
    dropdowns can still save other changes."""
    from django.utils.translation import gettext

    def value(field, default=''):
        return attrs[field] if field in attrs else getattr(instance, field, default)

    def changed(field):
        return field in attrs and (instance is None or attrs[field] != getattr(instance, field))

    country, region, council, errors = value('country', TANZANIA), value('region'), value('council'), {}
    if country not in COUNTRIES:
        errors['country'] = gettext('Pick a country from the list.')
        return errors
    if country != TANZANIA:
        return errors
    if region and (changed('region') or changed('country')) and region not in REGIONS:
        errors['region'] = gettext('Pick a region from the list.')
    if council and (changed('council') or changed('region') or changed('country')) \
            and council not in REGIONS.get(region, ()):
        errors['council'] = gettext('Pick a council of the chosen region.')
    return errors


def locations():
    """{countries: [{code, name}], regions: [{region, councils}]}, sorted,
    for the dropdowns. The regions are Tanzania's."""
    return {
        'countries': [{'code': code, 'name': name} for code, name in sorted(COUNTRIES.items(), key=lambda c: c[1])],
        'regions': [{'region': region, 'councils': sorted(councils)} for region, councils in sorted(REGIONS.items())],
    }
