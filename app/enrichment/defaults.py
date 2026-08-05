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
 'The two product complimentary variables must each notice a DIFFERENT, specifically NAMED thing '
 'from a DIFFERENT angle (one a named product/feature/service; the other a named '
 'project/client/recent work). Never repeat the same subject, observation, or question across the '
 'two.',
 "Every product complimentary is at most 20 words, pays a SUBTLE compliment (observe, don't gush; "
 "never 'incredibly impressive'), and ALWAYS ends with a genuine, curious question. Reference "
 'something the owner is clearly proud of, so they want to reply.',
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
  'purpose': 'First angle: a specifically NAMED product, feature, or service the company is '
             'clearly proud of. Subtle compliment, ends with a question. Maximum 20 words.',
  'guidance': 'Find the most distinctive NAMED product, feature, tool, or core service on their '
              'site (something with a name, something they would call by name). Pay a SUBTLE, '
              'specific compliment about it (what makes it practical, sharp, distinctive), never '
              "gush, never 'incredibly impressive'. Then ask ONE genuine question that a proud "
              "owner would want to answer. Start with 'Your'. Use '&' in lists. Must be a "
              'DIFFERENT subject than Product Complimentary 2. Hard cap 20 words.',
  'angle': 'a specifically named product / feature / tool / core service they are proud of',
  'min_words': 10,
  'max_words': 20,
  'rules': ['At most 20 words. Count before returning.',
            'Name ONE specific product/feature/tool/core service (something with a name).',
            "Compliment SUBTLY; never 'incredibly impressive', never gush.",
            'ALWAYS end with a genuine, curious question a proud owner would answer.',
            'Must be a DIFFERENT subject than Product Complimentary 2.',
            "Start with 'Your'. Use '&' in lists. No em dash."],
  'examples': ['Your LangTest framework for evaluating & red-teaming models is a sharp focus. Is '
               'that your flagship tool?',
               'Your dealer locator & part search setup looks genuinely practical. Is that a core '
               'part of the site?',
               'Your self-erecting cranes look built for tight sites. Are those your most '
               'requested models?',
               'Your real-time market intelligence in TheListingHub stands out. Is that the core '
               'of the platform?',
               'Your System Safety Program Plan development looks like a core compliance service. '
               'Is that a main offering?'],
  'enabled': True},
 {'label': 'Product Complimentary 2',
  'name': 'product_complimentary_2',
  'purpose': 'Second angle: a specifically NAMED project, client, case study, or recent work, '
             'different from #1. Subtle compliment, ends with a question. Maximum 20 words.',
  'guidance': 'Point to a NAMED piece of work: a project, a featured client, a case study, or a '
              'recent build, DIFFERENT from whatever Product Complimentary 1 used. Pay a SUBTLE, '
              'specific compliment (it stands out, it is a niche focus, it was a real win), never '
              "gush. Then ask ONE genuine question, different from #1's, that the owner would be "
              "proud to answer. Start with 'Your'. Use '&' in lists. Hard cap 20 words.",
  'angle': 'a specifically named project / featured client / case study / recent work (not the '
           'subject used in #1)',
  'min_words': 10,
  'max_words': 20,
  'rules': ['At most 20 words. Count before returning.',
            'Name a specific PROJECT / CLIENT / case study / recent work, not the subject from #1.',
            'Compliment SUBTLY; never gush.',
            "ALWAYS end with a genuine, curious question, different from #1's.",
            'Must be a DIFFERENT subject than Product Complimentary 1.',
            "Start with 'Your'. Use '&' in lists. No em dash."],
  'examples': ['Your AgentTalk work on secure agent-to-agent communication is a specific niche. '
               'Was that built in-house?',
               'Your 78 Fort Pl project stands out in the portfolio. Is that your main spotlight '
               'build?',
               'Your Klaviyo rebuild for Pharmstrong that revived daily revenue is real work. Was '
               'that a big win?',
               'Your Steve McQueen Year 3 project caught my eye. Is that one of your proudest '
               'collaborations?',
               "Your work scaling Spotify's ad business across 80+ markets is serious range. Was "
               'that a landmark account?'],
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
