"""System-wide DEFAULT enrichment variables.

These output variables are baked into the product: every workspace gets them by
default, in this exact order, with the SAME definitions, without any profile build
or prompt paste. A workspace may toggle a variable off ("enabled": False) or
override/append its own variables, but if it never customizes, these are what the
writer produces. Keeping the definitions here (not in per-workspace DB rows) is
what makes them global and consistent.

value_proposition and any other client-specific variables are intentionally NOT
here; those are decided per client/workspace.
"""

DEFAULT_GLOBAL_RULES = ["Subject line: a short Title Case label (2 to 6 words) naming the prospect's niche, market, or "
 "focus, joined with '&' (e.g. 'Hospitality & Tourism Brands', 'Industrial Brands & Developers'). "
 'It should feel relevant to them and hint what the email is about. No company name, no full '
 'sentence, no ending punctuation, no salesy/spam words, no em dash.',
 "Write in polished, articulate professional English (C1) — an expert copywriter's register. Never "
 'dumb the language down.',
 'Perfect grammar and spelling in every variable. Read it back before finishing.',
 'NEVER use an em dash (—) anywhere, in any variable. This is crucial. Use a comma, period, or '
 "'and' instead.",
 'Sound like one sharp founder emailing another: friendly, observant, engaging enough to earn a '
 'reply. Never a generic sales pitch, never robotic.',
 "Be specific and clearly researched: name the prospect's real product, project, client, or result "
 'from their site. Never generic praise, never invented facts.',
 'NEVER repeat the same fact, subject, client, project, or number across variables. Each variable '
 '(first line, both compliments, value proposition) must talk about a DIFFERENT thing. If the '
 'first line uses a company or result, no compliment or value proposition may reuse it, and the '
 'two compliments must be about two different things.',
 'Use numbers RARELY, only when the number itself is the point. If a number does not matter, leave '
 'it out entirely. When you do use a large number, round and shorten it: write 114,387,383 as '
 "'114M+' (or 'over 100 million') and 70,910 as '70K+'. Never write out a long exact figure.",
 "In lists, use '&' rather than 'and' (e.g. 'buying, selling, & financing').",
 'Personalized first line is NEVER above 20 words. Open warm, like a founder who actually looked: '
 "start with 'Loved how...', 'Your...', or 'Noticed your...', name ONE specific real thing about "
 'their work/approach, and pay it a genuine compliment (words like elite, sharp, rare, memorable, '
 'purpose-driven are fine). It can be two short clauses. Stay grounded and specific, never gush '
 "('impressive', 'incredible', 'world-class', 'blown away'), no question, no pitch, never a "
 'blog-title.',
 'Both product complimentary variables use the SAME format: a subtle observation about ONE '
 'specific thing, then a yes/no question. They differ ONLY in content, never in structure.',
 'Every product complimentary MUST end with a question that can be answered yes or no. Start it '
 "with 'Is that', 'Is this', 'Is it', or 'Are these'. NEVER an open-ended question ('What', 'How', "
 "'Why', 'Do you').",
 'The two product complimentary variables must each pick a DIFFERENT specific thing from the site. '
 'Same format, different subject and different question.',
 "Target customers is ALWAYS exactly three distinct segments in the format 'target1, target2, & "
 "target3'. Never two, never four.",
 'Do not reference our own service by name in the first line or the compliments; those are about '
 'THE PROSPECT. In the value proposition, WE offer OUR service TO the prospect, never pitch the '
 "prospect's own service back to them."]

DEFAULT_VARIABLE_ORDER = ['subject_line',
 'personalized_first_line',
 'product_complimentary_1',
 'product_complimentary_2',
 'ideal_customers',
 'target_customers',
 'company_category']

DEFAULT_FORMATS = [{'label': 'Subject Line',
  'name': 'subject_line',
  'purpose': "A short Title Case subject that names the prospect's niche/market/focus, so it feels "
             'relevant to them and hints what the email is about.',
  'guidance': "Write a short Title Case subject (2 to 6 words) naming the prospect's category, "
              'target market, or focus area, grounded in what they actually do. Join two facets '
              "with '&' (e.g. 'Hospitality & Tourism Brands', 'Industrial Brands & Developers', "
              "'Golf Brands & Tournament Series', 'Education & Community Groups'). It should tell "
              'the reader the email is about their space. No company name, no full sentence, no '
              'ending punctuation, no salesy words (free, offer, quick question), no em dash.',
  'min_words': 2,
  'max_words': 6,
  'rules': ['Title Case, 2 to 6 words.',
            "Name the prospect's niche / market / focus, grounded in their site.",
            "Join two facets with '&'.",
            'No company name, no full sentence, no ending punctuation.',
            'No salesy/spam words (free, offer, quick question, guaranteed). No em dash.'],
  'examples': ['Hospitality & Tourism Brands',
               'Industrial Brands & Developers',
               'Golf Brands & Tournament Series',
               'Education & Community Groups',
               'eCommerce & Retention Brands',
               'Heavy Equipment & Dealers'],
  'enabled': True},
 {'label': 'Personalized First Line',
  'name': 'personalized_first_line',
  'purpose': 'A warm, specific opener that names one real thing about the prospect and pays it a '
             'genuine compliment, like a founder who actually looked at their site. Maximum 20 '
             'words.',
  'guidance': "Open warm and human. Start with 'Loved how...', 'Your...', or 'Noticed your...'. "
              'Name ONE specific, real thing about their work, approach, product, or a named '
              'client/project from the site, and pay it a genuine compliment (elite, sharp, rare, '
              'memorable, purpose-driven, clever all work). It can be two short clauses, e.g. '
              "'Loved how X, your Y feels Z'. Keep it grounded and specific, never gush "
              "('impressive', 'incredible', 'world-class', 'blown away'). Use '&' in lists. Hard "
              'cap 20 words. No question, no pitch, no em dash, never a blog/article title.',
  'min_words': 8,
  'max_words': 20,
  'rules': ['NEVER above 20 words. Count before returning.',
            "Start with 'Loved how', 'Your', or 'Noticed your'.",
            'Name one specific real thing (approach, product, named client/project) and pay it a '
            'genuine compliment.',
            "Warm but not gushing: no 'impressive', 'incredible', 'world-class', 'blown away'.",
            "Two short clauses are fine. Use '&' not 'and' in lists.",
            'No question, no pitch, no em dash. Never personalize off a blog/article title.'],
  'examples': ['Loved how Lure blends data, strategy & storytelling into a MarTech stack built to '
               'drive bookings.',
               'Your bold industrial creative gives construction brands a fearless edge, '
               "RavenBuilt's rebrand was seriously memorable.",
               'Your full-scale launches for golf brands like SuperStroke are elite, mixing niche '
               'culture & polish rarely seen.',
               'Noticed your public health campaigns lean hard on community, your Cleveland '
               'schools work felt genuinely purpose-driven.',
               'Loved how your studio turns dense research into clean UX, the Creativity Exchange '
               'project really stood out.',
               'Your one-stop setup for buying, selling & financing heavy equipment is a genuinely '
               'smart, practical build.'],
  'enabled': True},
 {'label': 'Product Complimentary 1',
  'name': 'product_complimentary_1',
  'purpose': 'Notice ONE specific thing on their site, pay a subtle observation-as-compliment, '
             'then ask a yes/no question. Feels researched, not gushing. Same format as Product '
             'Complimentary 2; only the content differs.',
  'guidance': 'Point to ONE specific, named thing on their site (a product, feature, service, '
              'section, project, or setup). Make a SUBTLE observation about it that reads as a '
              "quiet compliment ('keeps the process in one place', 'is practical', 'stands out', "
              "'is very specific', 'keeps the work front & center'). Never gush, never 'incredibly "
              "impressive'. Then ask ONE yes/no question, starting with 'Is that', 'Is this', 'Is "
              "it', or 'Are these'. Start the line with 'Your'. Use '&' in lists. Pick a DIFFERENT "
              'subject than Product Complimentary 2.',
  'min_words': 12,
  'max_words': 22,
  'rules': ["Start with 'Your'.",
            'Subtle observation about ONE specific named thing; the observation IS the compliment. '
            'Never gush.',
            "End with a YES/NO question starting 'Is that', 'Is this', 'Is it', or 'Are these'.",
            "Never an open-ended question ('What', 'How', 'Why').",
            'Pick a DIFFERENT subject than Product Complimentary 2 (same format, different '
            'content).',
            "Use '&' in lists. No em dash. At most 22 words."],
  'examples': ['Your mix of equipment buying, sales, & financing keeps the process in one place. '
               'Is that the main reason customers come back?',
               'Your featured projects section keeps the work front & center. Is 78 Fort Pl your '
               'main spotlight project?',
               'Your dealer login, dealer locator, & part search setup is practical. Is the dealer '
               'locator a core part of the site?',
               'Your homepage keeps the cash offer path & the investment property path separate. '
               'Is that the main way people use it?',
               'Your mental fitness training and leadership EQ work is clearly organized. Is the '
               'custom proposal part of every engagement?',
               'Your site keeps the focus on grant writing, capital campaigns, & transition '
               'management. Is that the main mix you want people to notice?',
               'Your System Safety Program Plan (SSPP) Development looks like a core compliance '
               'service. Is that one of the main offerings?',
               'Your Classic Shift is a very specific product. Is that the main item people start '
               'with?',
               'Your real-time shared market intelligence stands out. Is that a core part of '
               'TheListingHub™?',
               'Your property matching for solo buyers is interesting. Is that part of the main '
               'ownership flow?'],
  'enabled': True},
 {'label': 'Product Complimentary 2',
  'name': 'product_complimentary_2',
  'purpose': 'Identical format to Product Complimentary 1: notice ONE specific thing, subtle '
             'observation-as-compliment, then a yes/no question. Only the subject and question '
             'differ from Complimentary 1.',
  'guidance': 'Same format as Product Complimentary 1. Point to a DIFFERENT specific, named thing '
              'on their site (a different product, feature, service, section, project, or setup '
              'than Complimentary 1 used). Make a SUBTLE observation that reads as a quiet '
              "compliment, never gush, never 'incredibly impressive'. Then ask ONE yes/no "
              "question, starting with 'Is that', 'Is this', 'Is it', or 'Are these'. Start the "
              "line with 'Your'. Use '&' in lists.",
  'min_words': 12,
  'max_words': 22,
  'rules': ["Start with 'Your'.",
            'Same format as Product Complimentary 1; only the subject and question differ.',
            'Subtle observation about ONE specific named thing; never gush.',
            "End with a YES/NO question starting 'Is that', 'Is this', 'Is it', or 'Are these'.",
            "Never an open-ended question ('What', 'How', 'Why').",
            'Pick a DIFFERENT subject than Product Complimentary 1.',
            "Use '&' in lists. No em dash. At most 22 words."],
  'examples': ['Your mix of equipment buying, sales, & financing keeps the process in one place. '
               'Is that the main reason customers come back?',
               'Your featured projects section keeps the work front & center. Is 78 Fort Pl your '
               'main spotlight project?',
               'Your dealer login, dealer locator, & part search setup is practical. Is the dealer '
               'locator a core part of the site?',
               'Your homepage keeps the cash offer path & the investment property path separate. '
               'Is that the main way people use it?',
               'Your mental fitness training and leadership EQ work is clearly organized. Is the '
               'custom proposal part of every engagement?',
               'Your site keeps the focus on grant writing, capital campaigns, & transition '
               'management. Is that the main mix you want people to notice?',
               'Your System Safety Program Plan (SSPP) Development looks like a core compliance '
               'service. Is that one of the main offerings?',
               'Your Classic Shift is a very specific product. Is that the main item people start '
               'with?',
               'Your real-time shared market intelligence stands out. Is that a core part of '
               'TheListingHub™?',
               'Your property matching for solo buyers is interesting. Is that part of the main '
               'ownership flow?'],
  'enabled': True},
 {'label': 'Ideal Customers',
  'name': 'ideal_customers',
  'purpose': 'The kind of customers the prospect itself serves or wants more of. Kept as-is. Used '
             'to make the value proposition feel researched.',
  'guidance': 'Name the specific type of customers THIS prospect serves or would want more of, '
              'based on their site (industries, buyer types, segments). Specific, not generic.',
  'min_words': 3,
  'max_words': 8,
  'rules': ['Specific buyer/segment types the prospect serves.', 'No generic labels. No em dash.'],
  'examples': ['DTC brands struggling with retention',
               'public-sector organizations & higher-ed institutions',
               'VC-backed startups needing fast MVPs'],
  'enabled': True},
 {'label': 'Target Customers',
  'name': 'target_customers',
  'purpose': 'Exactly three specific industries or buyer targets the prospect sells to, as a clean '
             'list. Slots straight into an email mid-sentence.',
  'guidance': "Give exactly THREE distinct industries or buyer targets in the format 'target1, "
              "target2, & target3'. Source them in this priority order: (1) if the site EXPLICITLY "
              'names the industries or buyers it serves, use those; (2) if not explicit, use the '
              'industries of their named clients or case studies (the type of big clients they '
              'have worked with before); (3) if neither, infer from the kind of service or product '
              'they provide. Always three, always distinct, always specific buyer or industry '
              "types, never generic ('businesses', 'clients', 'companies').",
  'format': '{{target1}}, {{target2}} & {{target3}}',
  'sourcing_priority_order': ['Explicitly named on the site (industries served / who it is for)',
                              'The industries of their named clients or case studies (who they '
                              'have worked with)',
                              'Inferred from the kind of service or product they provide'],
  'min_words': 4,
  'max_words': 12,
  'rules': ['ALWAYS exactly three targets, never two, never four.',
            "Format: 'target1, target2, & target3' — comma between the first two, '&' before the "
            'last.',
            'Three DISTINCT segments, each a specific industry or buyer type.',
            "No generic labels ('businesses', 'clients', 'companies').",
            "Follow the sourcing priority: explicit first, then their clients' industries, then "
            'service type.',
            'No em dash.'],
  'examples': ['Construction owners, heavy truck operators, & equipment buyers',
               'Manufactured housing investors, institutional capital partners, & portfolio '
               'decision makers',
               'AI product teams, ML platform engineers, & enterprise data leaders',
               'Education boards, cultural institutions, & nonprofit leaders'],
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
  'rules': ['Specific, self-descriptive category.', 'No generic labels. No em dash.'],
  'examples': ['eCommerce marketing agencies',
               'custom home builders',
               'leak detection & repair companies'],
  'enabled': True}]


def effective_formats(custom):
    """Merge a workspace's saved formats over the system defaults.

    Guarantees the default variables are ALWAYS present and in canonical order. A
    workspace entry with a matching name overrides the default's fields (e.g.
    toggling enabled, tweaking guidance); the code default is the base so newly
    added keys are inherited. Any extra custom variables (value_proposition, etc.)
    are appended after, preserving their saved order.
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
