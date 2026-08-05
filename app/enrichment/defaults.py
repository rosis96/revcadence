"""System-wide DEFAULT enrichment variables.

These six output variables are baked into the product: every workspace gets them
by default, in this exact order, with the SAME definitions, without any profile
build or prompt paste. A workspace may toggle a variable off ("enabled": False)
or override/append its own variables, but if it never customizes, these are what
the writer produces. Keeping the definitions here (not in per-workspace DB rows)
is what makes them global and consistent.

value_proposition and any other client-specific variables are intentionally NOT
here; those are decided per client/workspace.
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
 "In lists, use '&' rather than 'and' (e.g. 'buying, selling, & financing').",
 'Personalized first line is NEVER above 20 words. It is a neutral, factual observation of what '
 'the company actually does or sells, grounded in a real named product, client, project, or '
 'segment from their site. Never personalize off a blog-post title, an article headline, or a '
 'generic tagline.',
 'Both product complimentary variables use the SAME format: a subtle observation about ONE '
 'specific thing, then a yes/no question. They differ ONLY in content, never in structure.',
 'Every product complimentary MUST end with a question that can be answered yes or no. Start the '
 "question with 'Is that', 'Is this', or 'Are these'. NEVER ask an open-ended question ('What is', "
 "'How has', 'Why do', 'How does').",
 'The two product complimentary variables must each pick a DIFFERENT specific thing from the site. '
 'Same format, different subject and different question.',
 "Target customers is ALWAYS exactly three distinct segments in the format 'target1, target2, & "
 "target3'. Never two, never four.",
 'Do not reference our own service by name in the first line or the compliments; those are about '
 'THE PROSPECT. In the value proposition, WE offer OUR service TO the prospect, never pitch the '
 "prospect's own service back to them."]

DEFAULT_VARIABLE_ORDER = ['personalized_first_line',
 'product_complimentary_1',
 'product_complimentary_2',
 'ideal_customers',
 'target_customers',
 'company_category']

DEFAULT_FORMATS = [{'label': 'Personalized First Line',
  'name': 'personalized_first_line',
  'purpose': 'A tight, neutral, factual observation of what the company actually does or sells. '
             'Proves we looked at their site. No flattery, no pitch, no filler. Maximum 20 words.',
  'guidance': 'In one short sentence, state factually what their business or site centers on: the '
              'core thing they do, sell, or are known for, anchored to a REAL named specific from '
              "the site (a product, client, project, segment, or number). Start with 'Your'. Use "
              "'&' in lists. Ground it in what the COMPANY does, never in a blog-post title or "
              "article headline. No praise words ('impressed', 'showcasing', 'turned heads'), no "
              "question, no pitch. Hard cap 20 words. Cut every filler word ('providing a "
              "comprehensive overview of', 'across various industries', etc.).",
  'min_words': 8,
  'max_words': 20,
  'rules': ['NEVER above 20 words. Count before returning.',
            "Start with 'Your' or the company name.",
            'Neutral factual observation of what they actually do or sell, not praise.',
            'Anchor to a real named product, client, project, segment, or number.',
            'Never personalize off a blog/article title or generic tagline.',
            "No filler ('comprehensive overview', 'various industries'). No question. No pitch. No "
            'em dash.',
            "Use '&' not 'and' in lists."],
  'examples': ['Your site centers on pre-owned heavy equipment, with buying, selling, & financing '
               'all in one place.',
               'Your homepage splits cleanly between cash offers on houses & off-market investment '
               'property deals.',
               'Delta Tech shows over 500 auxiliary light, headlight, & light bar models across '
               'automotive & truck segments.',
               'Your platform builds and red-teams AI models, with LangTest & AgentTalk as the '
               'core tools.',
               'Your work centers on commercial & residential projects like 78 Fort Pl & 60-62 Van '
               'Duzer St.',
               'Your studio focuses on UX & service design for education and cultural clients like '
               'Southbank Centre.'],
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
              "impressive'. Then ask ONE yes/no question, starting with 'Is that', 'Is this', or "
              "'Are these'. Start the line with 'Your'. Use '&' in lists. Pick a DIFFERENT subject "
              'than Product Complimentary 2.',
  'min_words': 12,
  'max_words': 22,
  'rules': ["Start with 'Your'.",
            'Subtle observation about ONE specific named thing; the observation IS the compliment. '
            'Never gush.',
            "End with a YES/NO question starting 'Is that', 'Is this', or 'Are these'.",
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
              "question, starting with 'Is that', 'Is this', or 'Are these'. Start the line with "
              "'Your'. Use '&' in lists.",
  'min_words': 12,
  'max_words': 22,
  'rules': ["Start with 'Your'.",
            'Same format as Product Complimentary 1; only the subject and question differ.',
            'Subtle observation about ONE specific named thing; never gush.',
            "End with a YES/NO question starting 'Is that', 'Is this', or 'Are these'.",
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
