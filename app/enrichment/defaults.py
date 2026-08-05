"""System-wide DEFAULT enrichment variables.

These six output variables are baked into the product: every workspace gets them
by default, in this exact order, with the SAME definitions, without any profile
build or prompt paste. A workspace may toggle a variable off ("enabled": False)
or override/append its own variables, but if it never customizes, these are what
the writer produces. Keeping the definitions here (not in per-workspace DB rows)
is what makes them global and consistent.

value_proposition and any other client-specific variables are intentionally NOT
here — those are decided per client/workspace.
"""

DEFAULT_GLOBAL_RULES = ["Write in polished, articulate professional English (C1) — an expert copywriter's register. Never "
 'dumb the language down.',
 'Perfect grammar and spelling in every variable. Read it back before finishing.',
 'NEVER use an em dash (—) anywhere, in any variable. This is crucial. Use a comma, period, or '
 "'and' instead.",
 'Sound like one sharp founder emailing another: friendly, observant, engaging enough to earn a '
 'reply. Never a generic sales pitch, never robotic.',
 "Be specific and clearly researched: name the prospect's real product, project, client, or result "
 'from their site. Never generic praise, never invented facts.',
 'Do not reference our own service by name in the first line or compliments; those are about THE '
 'PROSPECT.',
 'In the value proposition, WE (Revcadence) offer OUR service TO the prospect. Never pitch the '
 "prospect's own service back to them.",
 "In lists, use '&' rather than 'and' (e.g. 'buying, selling, & financing').",
 'Personalized first line = a NEUTRAL, factual observation of what their site/business centers on. '
 "No flattery, no 'impressed', no 'showcasing', no 'turned heads', no pitch. It should read like "
 'you actually looked at their site.',
 'The two product complimentary variables must each notice a DIFFERENT thing from a DIFFERENT '
 'angle. Never repeat the same feature, the same observation, or the same question across the two.',
 "Product complimentary = notice ONE specific thing and pay a SUBTLE compliment (observe, don't "
 "gush), then ask a genuine, curious question. Never 'incredibly impressive'. Do not just list a "
 'service.',
 "Target customers must ALWAYS be exactly three, in the format 'target1, target2, & target3'. "
 'Three distinct segments, never two, never four.']

DEFAULT_VARIABLE_ORDER = ['personalized_first_line',
 'product_complimentary_1',
 'product_complimentary_2',
 'ideal_customers',
 'target_customers',
 'company_category']

DEFAULT_FORMATS = [{'label': 'Personalized First Line',
  'name': 'personalized_first_line',
  'purpose': "A neutral, factual observation of what the prospect's site or business centers on. "
             'Reads like you actually looked at their site. No flattery, no pitch, no '
             'embellishment.',
  'guidance': 'State, factually and specifically, what their site or business centers on — the 2-3 '
              'main things they do, sell, or focus on, with real named specifics pulled from the '
              "site (projects, products, segments, models, numbers). Start with 'Your site centers "
              "on...', 'Your homepage...', 'Your [specific thing]...', or '[Company] shows...'. "
              "Use '&' in lists. Do NOT praise, do NOT say 'impressed' / 'showcasing' / 'turned "
              "heads', do NOT pitch. Just show you read their site.",
  'min_words': 10,
  'max_words': 22,
  'rules': ["Start with 'Your' or the company name.",
            'Neutral factual observation, NOT praise or embellishment.',
            'Name real specifics from the site (projects, products, segments, numbers).',
            "Use '&' not 'and' in lists.",
            'No pitch, no question. One sentence. No em dash.'],
  'examples': ['Your site centers on pre-owned heavy equipment, with buying, selling, & financing '
               'all in one place.',
               'Your site centers on commercial, residential, & assisted housing projects like 78 '
               'Fort Pl and 60-62 Van Duzer St.',
               'Delta Tech Industries shows over 500 auxiliary light, headlight, & light bar '
               'models across automotive, military, & commercial truck segments.',
               'Your homepage splits clearly between cash offers on houses & off-market investment '
               'property deals.',
               'Your site centers mental fitness training, leadership EQ, & emotional resilience '
               'workshops for organizations.',
               'Your site centers grant writing, capital campaigns, & transition management for '
               'culture & community-building organizations.'],
  'enabled': True},
 {'label': 'Product Complimentary 1',
  'name': 'product_complimentary_1',
  'purpose': 'First angle: notice ONE core offering, product, or service setup on their site, pay '
             'a SUBTLE compliment, then ask a genuine question. Feels like real research, not '
             'gushing.',
  'guidance': "Pick the prospect's CORE offering or how their main service/product setup is "
              'organized (e.g. their mix of services, their main product line, how their process '
              "is structured). Add a SUBTLE positive observation ('keeps the process in one "
              "place', 'is practical', 'stands out'), never gush. Then ask ONE genuine, curious "
              "question. Start with 'Your'. Use '&' in lists. This must focus on a DIFFERENT thing "
              'than Product Complimentary 2.',
  'angle': 'core offering / main service or product setup / how the process is organized',
  'min_words': 12,
  'max_words': 26,
  'rules': ["Start with 'Your'.",
            'Focus on the CORE offering or main service/product setup.',
            "Compliment SUBTLY — observe, do not gush; never 'incredibly impressive'.",
            'Do NOT just list a service; the subtle observation IS the compliment.',
            'End with a genuine, curious question.',
            'Must notice a DIFFERENT thing than Product Complimentary 2.',
            "Use '&' in lists. No em dash."],
  'examples': ['Your mix of equipment buying, sales, & financing keeps the process in one place. '
               'Is that the main reason customers come back?',
               'Your dealer login, dealer locator, & part search setup is practical. Is the dealer '
               'locator a core part of the site?',
               'Your homepage keeps the cash offer path & the investment property path separate. '
               'Is that the main way people use it?',
               'Your System Safety Program Plan (SSPP) Development looks like a core compliance '
               'service. Is that one of the main offerings?'],
  'enabled': True},
 {'label': 'Product Complimentary 2',
  'name': 'product_complimentary_2',
  'purpose': 'Second angle: notice a DIFFERENT specific element — a named project, featured tool, '
             'client result, or standout page — pay a SUBTLE compliment, then ask a genuine '
             'question.',
  'guidance': 'Pick a DIFFERENT, more specific element than Product Complimentary 1: a named '
              'project, a featured case study or client, a specific tool or page, a standout '
              "detail. Add a SUBTLE positive observation ('keeps the work front & center', 'stands "
              "out', 'is very specific'), never gush. Then ask ONE genuine, curious question, "
              "different from the first. Start with 'Your'. Use '&' in lists.",
  'angle': 'a specific named project / featured tool / client result / standout page or detail',
  'min_words': 12,
  'max_words': 26,
  'rules': ["Start with 'Your'.",
            'Focus on a SPECIFIC named element (project, tool, client, page), not the core service '
            'already used in #1.',
            "Compliment SUBTLY — observe, do not gush; never 'incredibly impressive'.",
            'End with a genuine, curious question, different from the #1 question.',
            'Must notice a DIFFERENT thing than Product Complimentary 1.',
            "Use '&' in lists. No em dash."],
  'examples': ['Your featured projects section keeps the work front & center. Is 78 Fort Pl your '
               'main spotlight project?',
               'Your real-time shared market intelligence stands out. Is that a core part of '
               'TheListingHub™?',
               "Your case study on Pharmstrong's revenue jump is specific. Was that rebuild built "
               'fully in-house?',
               'Your resource library with the SSPP templates is a nice touch. Do prospects find '
               'you through those?'],
  'enabled': True},
 {'label': 'Ideal Customers',
  'name': 'ideal_customers',
  'purpose': 'The kind of customers the prospect itself serves or wants more of — used to make the '
             'value proposition feel researched.',
  'guidance': 'Name the specific type of customers THIS prospect serves or would want more of, '
              'based on their site (industries, buyer types, segments). Specific, not generic.',
  'min_words': 3,
  'max_words': 8,
  'rules': ['Specific buyer/segment types the prospect serves.', 'No em dash.'],
  'examples': ['DTC brands struggling with retention',
               'public-sector organizations and higher-ed institutions',
               'VC-backed startups needing fast MVPs'],
  'enabled': True},
 {'label': 'Target Customers',
  'name': 'target_customers',
  'purpose': 'Exactly three specific industries or buyer targets the prospect sells to, written as '
             'a clean list for use mid-sentence in the value proposition.',
  'guidance': "Give exactly THREE distinct industries or buyer targets, in the format 'target1, "
              "target2, & target3'. Source them in this priority order: (1) if the site EXPLICITLY "
              'names the industries or buyers it serves, use those; (2) if not explicit, infer '
              'from their case studies, featured clients, or portfolio; (3) if neither, infer from '
              'the kind of service or product they provide. Always three, always distinct, always '
              "specific buyer/industry types (not generic like 'businesses' or 'clients').",
  'format': '{{target1}}, {{target2}} & {{target3}}',
  'sourcing_priority_order': ['Explicitly named on the site (industries served / who it is for)',
                              'Inferred from case studies, featured clients, or portfolio',
                              'Inferred from the kind of service or product they provide'],
  'min_words': 4,
  'max_words': 12,
  'rules': ['ALWAYS exactly three targets, never two, never four.',
            "Format: 'target1, target2, & target3' — comma between the first two, '&' before the "
            'last.',
            'Three DISTINCT segments, each a specific industry or buyer type.',
            "No generic labels like 'businesses', 'clients', 'companies'.",
            'Follow the sourcing priority: explicit first, then case studies, then service type.',
            'No em dash.'],
  'examples': ['Construction owners, heavy truck operators, & equipment buyers',
               'Manufactured housing investors, institutional capital partners, & portfolio '
               'decision makers',
               'eCommerce founders, retention marketers, & DTC operators',
               'Transit agencies, safety compliance officers, & municipal transportation planners'],
  'enabled': True},
 {'label': 'Company Category',
  'name': 'company_category',
  'purpose': 'The specific category the prospect would use to describe itself, plural where '
             'natural. Used inside the value proposition.',
  'guidance': 'Write the specific category this company would use for itself, based on what it '
              "sells or delivers. Plural where natural. Avoid generic labels like 'businesses', "
              "'service providers', 'B2B companies', 'professional services'.",
  'min_words': 2,
  'max_words': 5,
  'rules': ['Specific, self-descriptive category.', 'No generic labels.', 'No em dash.'],
  'examples': ['eCommerce marketing agencies',
               'custom home builders',
               'leak detection and repair companies'],
  'enabled': True}]


def effective_formats(custom):
    """Merge a workspace's saved formats over the system defaults.

    Guarantees the six default variables are ALWAYS present and in canonical
    order. A workspace entry with a matching name overrides the default's fields
    (e.g. toggling enabled, tweaking guidance); the code default is the base so
    newly-added keys are inherited. Any extra custom variables (value_proposition,
    etc.) are appended after, preserving their saved order.
    """
    custom = [f for f in (custom or []) if isinstance(f, dict) and f.get("name")]
    by_name = {f["name"]: f for f in custom}
    out, seen = [], set()
    for d in DEFAULT_FORMATS:
        name = d["name"]
        seen.add(name)
        out.append({**d, **by_name[name]} if name in by_name else dict(d))
    for f in custom:
        if f["name"] not in seen:
            out.append(f)
    return out


def default_rule_lines():
    """The global output rules, one per line, to inject into the writer as the
    highest-priority master instructions in every workspace."""
    return list(DEFAULT_GLOBAL_RULES)
