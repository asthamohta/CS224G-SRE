"""
online_boutique_scenarios.py - Harder benchmark scenarios grounded in the
Google Online Boutique microservices application.

Services (from k8s manifests):
  frontend → checkoutservice, cartservice, productcatalogservice,
              currencyservice, recommendationservice, shippingservice, adservice
  checkoutservice → cartservice, currencyservice, emailservice,
                     paymentservice, productcatalogservice, shippingservice
  recommendationservice → productcatalogservice
  cartservice → redis
  adservice, paymentservice, emailservice, shippingservice, currencyservice,
  productcatalogservice → standalone leaves

Difficulty design:
  easy   (ob_001–ob_003): single service, explicit error, clear GitHub signal
  medium (ob_004–ob_006): 2-3 service cascade + one red-herring GitHub event
  hard   (ob_007–ob_010): silent/ambiguous failures, multi-service noise,
                           misleading GitHub deploys, requires trace reasoning

Each scenario adds:
  github_events  – list of GitHub JSONL event dicts (written to temp file at
                   runtime by online_boutique_data_generator.py)
  noise_events   – {service: [event]} to inject into non-root-cause nodes
                   so the LLM must sift through plausible-but-irrelevant signals
"""

from datetime import datetime, timezone, timedelta

_BASE_TS  = datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
_BASE_STR = _BASE_TS.strftime("%Y-%m-%d %H:%M:%S")

# Anchor timestamps used for GitHub event ingested_at
_T60  = (_BASE_TS - timedelta(minutes=60)).isoformat()   # 1 h before
_T30  = (_BASE_TS - timedelta(minutes=30)).isoformat()   # 30 min before
_T15  = (_BASE_TS - timedelta(minutes=15)).isoformat()   # 15 min before
_T5   = (_BASE_TS - timedelta(minutes=5)).isoformat()    # 5 min before  (red-herring zone)
_T2   = (_BASE_TS - timedelta(minutes=2)).isoformat()    # 2 min before  (red-herring zone)


def _scoring_points(component: str, reason: str, dt_str: str) -> str:
    return (
        f"The only predicted root cause component is {component}\n"
        f"The only predicted root cause reason is {reason}\n"
        f"The only root cause occurrence time is within 1 minutes "
        f"(i.e., <=1min) of {dt_str}"
    )


def _gh_push(service_id, title, commit_sha, files, ingested_at):
    """Build a minimal GitHub push event dict."""
    return {
        "ingested_at": ingested_at,
        "event_type": "push",
        "repo_owner": "google",
        "repo_name": "microservices-demo",
        "service_id": service_id,
        "watch_path_prefix": f"src/{service_id}",
        "commit_sha": commit_sha,
        "title": title,
        "url": f"https://github.com/google/microservices-demo/commit/{commit_sha}",
        "files": files,
    }


def _gh_pr(service_id, title, pr_number, files, ingested_at):
    """Build a minimal GitHub pull-request event dict."""
    return {
        "ingested_at": ingested_at,
        "event_type": "pull_request",
        "repo_owner": "google",
        "repo_name": "microservices-demo",
        "service_id": service_id,
        "watch_path_prefix": f"src/{service_id}",
        "pr_number": pr_number,
        "title": title,
        "url": f"https://github.com/google/microservices-demo/pull/{pr_number}",
        "files": files,
    }


def _noise_event(source, kind, summary, timestamp=None, payload=None):
    ts = timestamp or _BASE_TS.isoformat()
    return {
        "source": source,
        "kind": kind,
        "timestamp": ts,
        "summary": summary,
        "payload": payload or {},
    }


# ===========================================================================
# EASY SCENARIOS — single service, direct signal, clear GitHub deploy
# ===========================================================================

OB_EASY_001 = {
    "id": "ob_easy_001",
    "task_index": "task_1",
    "difficulty": "easy",
    "title": "cartservice Redis connection refused after config change",
    "description": (
        "A push to cartservice changed REDIS_ADDR to an unreachable host. "
        "cartservice cannot connect to Redis and returns 500 on every cart "
        "operation. frontend shows 500s on all add-to-cart actions. "
        "All other services are healthy."
    ),
    "topology": {
        "services": ["frontend", "cartservice", "redis", "checkoutservice"],
        "edges": [
            ("frontend", "cartservice"),
            ("frontend", "checkoutservice"),
            ("cartservice", "redis"),
        ],
    },
    "fault_injection": {
        "root_cause_service": "cartservice",
        "fault_type": "connection_refused",
        "silent": False,
        "error_message": (
            "redis.exceptions.ConnectionRefusedError: [Errno 111] "
            "Connection refused - host=redis-new.internal:6379 unreachable"
        ),
        "status_code_http": "500",
        "propagates_to": ["frontend"],
    },
    "observed_service": "frontend",
    "fault_start_ts": _BASE_TS,
    "ground_truth": {
        "root_cause_component": "cartservice",
        "root_cause_reason": "Redis connection refused due to misconfigured REDIS_ADDR in deployment",
    },
    "scoring_points": _scoring_points(
        "cartservice",
        "Redis connection refused due to misconfigured REDIS_ADDR in deployment",
        _BASE_STR,
    ),
    "github_events": [
        _gh_push(
            "cartservice",
            "chore: update REDIS_ADDR to new cluster endpoint",
            "e1a2b3c",
            [
                {
                    "filename": "src/cartservice/Dockerfile",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 1,
                    "patch": (
                        "@@ -14,7 +14,7 @@ ENV PORT=7070\n"
                        "-ENV REDIS_ADDR=redis.cart.svc.cluster.local:6379\n"
                        "+ENV REDIS_ADDR=redis-new.internal:6379\n"
                    ),
                }
            ],
            _T30,
        )
    ],
    "noise_events": {
        "checkoutservice": [
            _noise_event("otel", "info_log",
                         "PlaceOrder gRPC completed in 142ms",
                         payload={"http.status_code": "200"}),
        ],
    },
}


OB_EASY_002 = {
    "id": "ob_easy_002",
    "task_index": "task_2",
    "difficulty": "easy",
    "title": "paymentservice proto schema mismatch crash",
    "description": (
        "A merged PR updated the paymentservice proto schema, removing the "
        "'card_number' field that checkoutservice still sends. paymentservice "
        "crashes on every ChargeRequest with a proto unmarshal error. "
        "checkoutservice gets 500 on all PlaceOrder calls."
    ),
    "topology": {
        "services": ["frontend", "checkoutservice", "paymentservice"],
        "edges": [
            ("frontend", "checkoutservice"),
            ("checkoutservice", "paymentservice"),
        ],
    },
    "fault_injection": {
        "root_cause_service": "paymentservice",
        "fault_type": "proto_schema_mismatch",
        "silent": False,
        "error_message": (
            "FATAL: proto unmarshal error: required field 'card_number' not found "
            "in ChargeRequest - client is using deprecated schema v1"
        ),
        "status_code_http": "500",
        "propagates_to": ["checkoutservice", "frontend"],
    },
    "observed_service": "frontend",
    "fault_start_ts": _BASE_TS,
    "ground_truth": {
        "root_cause_component": "paymentservice",
        "root_cause_reason": "proto schema mismatch after removing card_number field from ChargeRequest",
    },
    "scoring_points": _scoring_points(
        "paymentservice",
        "proto schema mismatch after removing card_number field from ChargeRequest",
        _BASE_STR,
    ),
    "github_events": [
        _gh_pr(
            "paymentservice",
            "feat: migrate ChargeRequest to v2 schema (remove deprecated fields)",
            412,
            [
                {
                    "filename": "src/paymentservice/proto/payment.proto",
                    "status": "modified",
                    "additions": 4,
                    "deletions": 6,
                    "patch": (
                        "@@ -8,10 +8,8 @@ message ChargeRequest {\n"
                        "   Money amount = 1;\n"
                        "-  // deprecated: use card_info instead\n"
                        "-  string card_number = 2;\n"
                        "-  int32  card_expiry_year  = 3;\n"
                        "-  int32  card_expiry_month = 4;\n"
                        "+  CreditCardInfo card_info = 2;\n"
                        " }\n"
                    ),
                }
            ],
            _T15,
        )
    ],
    "noise_events": {
        "checkoutservice": [
            _noise_event("otel", "warn_log",
                         "Upstream paymentservice returned gRPC status INTERNAL on 3 consecutive calls",
                         payload={"grpc.status": "13"}),
        ],
    },
}


OB_EASY_003 = {
    "id": "ob_easy_003",
    "task_index": "task_3",
    "difficulty": "easy",
    "title": "productcatalogservice panic — missing products.json after redeploy",
    "description": (
        "A new container image for productcatalogservice was deployed without "
        "the product catalog data file. The service panics on startup when it "
        "cannot open /data/products.json. frontend, recommendationservice, "
        "and checkoutservice all receive RPC errors."
    ),
    "topology": {
        "services": [
            "frontend", "productcatalogservice",
            "recommendationservice", "checkoutservice",
        ],
        "edges": [
            ("frontend", "productcatalogservice"),
            ("frontend", "recommendationservice"),
            ("frontend", "checkoutservice"),
            ("recommendationservice", "productcatalogservice"),
            ("checkoutservice", "productcatalogservice"),
        ],
    },
    "fault_injection": {
        "root_cause_service": "productcatalogservice",
        "fault_type": "panic_missing_file",
        "silent": False,
        "error_message": (
            "FATAL: panic serving [::1]:3550: "
            "open /data/products.json: no such file or directory"
        ),
        "status_code_http": "500",
        "propagates_to": ["frontend", "recommendationservice", "checkoutservice"],
    },
    "observed_service": "frontend",
    "fault_start_ts": _BASE_TS,
    "ground_truth": {
        "root_cause_component": "productcatalogservice",
        "root_cause_reason": "service panic because products.json data file missing from container image",
    },
    "scoring_points": _scoring_points(
        "productcatalogservice",
        "service panic because products.json data file missing from container image",
        _BASE_STR,
    ),
    "github_events": [
        _gh_push(
            "productcatalogservice",
            "chore: bump base image to distroless/static:nonroot for security",
            "c9d8e7f",
            [
                {
                    "filename": "src/productcatalogservice/Dockerfile",
                    "status": "modified",
                    "additions": 2,
                    "deletions": 2,
                    "patch": (
                        "@@ -18,8 +18,8 @@ RUN go build -o /productcatalogservice .\n"
                        "-FROM gcr.io/distroless/base-debian12:nonroot\n"
                        "+FROM gcr.io/distroless/static:nonroot\n"
                        "-COPY --from=builder /data/products.json /data/products.json\n"
                        "+# Note: data files are now mounted via ConfigMap\n"
                        " COPY --from=builder /productcatalogservice /productcatalogservice\n"
                    ),
                }
            ],
            _T30,
        )
    ],
    "noise_events": {
        "recommendationservice": [
            _noise_event("otel", "warn_log",
                         "GetProduct RPC failed: rpc error: code = Unavailable "
                         "desc = connection refused to productcatalogservice",
                         payload={"grpc.status": "14"}),
        ],
        "checkoutservice": [
            _noise_event("otel", "warn_log",
                         "GetProduct RPC failed for product OLJCESPC7Z: Unavailable",
                         payload={"grpc.status": "14"}),
        ],
    },
}


# ===========================================================================
# MEDIUM SCENARIOS — cascade failures + one misleading GitHub event
# ===========================================================================

OB_MEDIUM_001 = {
    "id": "ob_medium_001",
    "task_index": "task_4",
    "difficulty": "medium",
    "title": "currencyservice N+1 API call pattern cascades to frontend & checkout",
    "description": (
        "A refactor in currencyservice introduced a sequential per-currency "
        "API call loop instead of a single batch call. P99 latency spiked to "
        "12 s. frontend and checkoutservice both timeout (504) waiting for "
        "currency conversions. "
        "A cartservice PR was also merged the same day (unrelated feature flag) "
        "and cartservice is healthy."
    ),
    "topology": {
        "services": [
            "frontend", "currencyservice",
            "checkoutservice", "cartservice",
        ],
        "edges": [
            ("frontend", "currencyservice"),
            ("frontend", "checkoutservice"),
            ("frontend", "cartservice"),
            ("checkoutservice", "currencyservice"),
        ],
    },
    "fault_injection": {
        "root_cause_service": "currencyservice",
        "fault_type": "high_latency_n_plus_one",
        "silent": False,
        "error_message": (
            "WARN: GetSupportedCurrencies sequential loop took 11823ms "
            "(33 currencies × 358ms each) - should use batch API call"
        ),
        "status_code_http": "504",
        "propagates_to": ["frontend", "checkoutservice"],
    },
    "observed_service": "frontend",
    "fault_start_ts": _BASE_TS,
    "ground_truth": {
        "root_cause_component": "currencyservice",
        "root_cause_reason": "N+1 sequential API call pattern causing extreme latency in currency conversion",
    },
    "scoring_points": _scoring_points(
        "currencyservice",
        "N+1 sequential API call pattern causing extreme latency in currency conversion",
        _BASE_STR,
    ),
    "github_events": [
        # Root-cause deploy — 30 min before incident
        _gh_push(
            "currencyservice",
            "refactor: switch currency rate fetch to per-currency calls for better error isolation",
            "a1b2c3d",
            [
                {
                    "filename": "src/currencyservice/server.js",
                    "status": "modified",
                    "additions": 18,
                    "deletions": 6,
                    "patch": (
                        "@@ -42,12 +42,24 @@ async function getSupportedCurrencies() {\n"
                        "-  const rates = await fetchAllRates();\n"
                        "-  return rates;\n"
                        "+  // Fetch each currency individually for isolated error handling\n"
                        "+  const currencies = await listSupportedCurrencies();\n"
                        "+  const rates = {};\n"
                        "+  for (const code of currencies) {\n"
                        "+    const r = await fetchRate(code);  // sequential — was batch\n"
                        "+    rates[code] = r;\n"
                        "+  }\n"
                        "+  return rates;\n"
                    ),
                }
            ],
            _T30,
        ),
        # Red-herring deploy — 5 min before incident, different service
        _gh_pr(
            "cartservice",
            "feat: add feature flag for cart item limit (capped at 50)",
            389,
            [
                {
                    "filename": "src/cartservice/src/CartService.cs",
                    "status": "modified",
                    "additions": 8,
                    "deletions": 2,
                    "patch": (
                        "@@ -78,6 +78,12 @@ public override async Task<AddItemResponse> AddItem(\n"
                        "+  if (FeatureFlags.CartItemLimit)\n"
                        "+  {\n"
                        "+    if (cart.Items.Count >= 50)\n"
                        "+      throw new RpcException(new Status(StatusCode.FailedPrecondition,\n"
                        "+        \"Cart item limit reached\"));\n"
                        "+  }\n"
                    ),
                }
            ],
            _T5,
        ),
    ],
    "noise_events": {
        "cartservice": [
            _noise_event("otel", "info_log",
                         "AddItem completed in 18ms - cart item limit check passed",
                         payload={"http.status_code": "200"}),
        ],
        "checkoutservice": [
            _noise_event("otel", "warn_log",
                         "RPC deadline exceeded calling currencyservice after 10001ms",
                         payload={"grpc.deadline_exceeded": True}),
        ],
    },
}


OB_MEDIUM_002 = {
    "id": "ob_medium_002",
    "task_index": "task_5",
    "difficulty": "medium",
    "title": "shippingservice O(n²) route algorithm times out checkout for large carts",
    "description": (
        "A new shipping cost algorithm iterates over all route permutations in "
        "O(n²) time. For carts with >10 items the calculation takes 8+ seconds, "
        "causing checkoutservice to receive timeout errors on PlaceOrder. "
        "frontend shows checkout failures for large carts. "
        "An unrelated emailservice config push happened around the same time."
    ),
    "topology": {
        "services": [
            "frontend", "checkoutservice",
            "shippingservice", "emailservice",
        ],
        "edges": [
            ("frontend", "checkoutservice"),
            ("checkoutservice", "shippingservice"),
            ("checkoutservice", "emailservice"),
        ],
    },
    "fault_injection": {
        "root_cause_service": "shippingservice",
        "fault_type": "cpu_exhaustion_bad_algorithm",
        "silent": False,
        "error_message": (
            "WARN: GetQuote took 8234ms for cart_size=15 "
            "- O(n²) route permutation loop detected (n=15, iterations=225)"
        ),
        "status_code_http": "504",
        "propagates_to": ["checkoutservice", "frontend"],
    },
    "observed_service": "frontend",
    "fault_start_ts": _BASE_TS,
    "ground_truth": {
        "root_cause_component": "shippingservice",
        "root_cause_reason": "O(n squared) shipping route algorithm causing timeout for large carts",
    },
    "scoring_points": _scoring_points(
        "shippingservice",
        "O(n squared) shipping route algorithm causing timeout for large carts",
        _BASE_STR,
    ),
    "github_events": [
        _gh_push(
            "shippingservice",
            "feat: improve shipping quote accuracy with multi-route comparison",
            "b4c5d6e",
            [
                {
                    "filename": "src/shippingservice/quote.go",
                    "status": "modified",
                    "additions": 22,
                    "deletions": 8,
                    "patch": (
                        "@@ -31,14 +31,28 @@ func GetQuote(items []*pb.CartItem) (float64, error) {\n"
                        "-  return baseRate * float64(len(items)), nil\n"
                        "+  // Compare all route combinations for best price\n"
                        "+  routes := generateAllRoutes(items)  // O(n!) warning: not bounded\n"
                        "+  bestCost := math.MaxFloat64\n"
                        "+  for _, r1 := range routes {\n"
                        "+    for _, r2 := range routes {\n"
                        "+      cost := calculateRouteCost(r1, r2)\n"
                        "+      if cost < bestCost { bestCost = cost }\n"
                        "+    }\n"
                        "+  }\n"
                        "+  return bestCost, nil\n"
                    ),
                }
            ],
            _T60,
        ),
        # Red herring — emailservice SMTP config, 2 min before
        _gh_push(
            "emailservice",
            "config: increase SMTP connection pool from 5 to 10",
            "f7a8b9c",
            [
                {
                    "filename": "src/emailservice/email_server.py",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 1,
                    "patch": (
                        "@@ -22,7 +22,7 @@ class EmailService:\n"
                        "-    SMTP_POOL_SIZE = 5\n"
                        "+    SMTP_POOL_SIZE = 10\n"
                    ),
                }
            ],
            _T2,
        ),
    ],
    "noise_events": {
        "emailservice": [
            _noise_event("otel", "info_log",
                         "SendOrderConfirmation completed - SMTP pool size=10",
                         payload={"smtp.pool_available": 10}),
        ],
        "checkoutservice": [
            _noise_event("otel", "warn_log",
                         "GetQuote RPC timeout after 10s waiting for shippingservice",
                         payload={"grpc.deadline_exceeded": True, "cart_size": 15}),
        ],
    },
}


OB_MEDIUM_003 = {
    "id": "ob_medium_003",
    "task_index": "task_6",
    "difficulty": "medium",
    "title": "adservice memory leak causes OOM restarts and frontend ad widget errors",
    "description": (
        "A new impression-caching feature in adservice accumulates entries without "
        "eviction. After 2 hours the container OOM-kills. Kubernetes restarts it, "
        "but the cycle continues every ~5 minutes. frontend GetAds RPCs fail "
        "intermittently. productcatalogservice had a separate caching improvement "
        "deployed around the same time but is healthy."
    ),
    "topology": {
        "services": ["frontend", "adservice", "productcatalogservice"],
        "edges": [
            ("frontend", "adservice"),
            ("frontend", "productcatalogservice"),
        ],
    },
    "fault_injection": {
        "root_cause_service": "adservice",
        "fault_type": "memory_leak_oom",
        "silent": False,
        "error_message": (
            "FATAL: Reached heap limit Allocation failed - "
            "JavaScript heap out of memory (impressionCache size=2.1GB)"
        ),
        "status_code_http": "503",
        "propagates_to": ["frontend"],
    },
    "observed_service": "frontend",
    "fault_start_ts": _BASE_TS,
    "ground_truth": {
        "root_cause_component": "adservice",
        "root_cause_reason": "unbounded in-memory impression cache causing OOM and repeated container crashes",
    },
    "scoring_points": _scoring_points(
        "adservice",
        "unbounded in-memory impression cache causing OOM and repeated container crashes",
        _BASE_STR,
    ),
    "github_events": [
        _gh_push(
            "adservice",
            "feat: cache ad impressions in-memory to reduce DB round-trips",
            "d1e2f3a",
            [
                {
                    "filename": "src/adservice/src/main/java/hipstershop/AdService.java",
                    "status": "modified",
                    "additions": 14,
                    "deletions": 2,
                    "patch": (
                        "@@ -55,8 +55,20 @@ class AdService {\n"
                        "+  // In-memory impression cache for performance\n"
                        "+  private final Map<String, AdImpression> impressionCache =\n"
                        "+      new ConcurrentHashMap<>();  // TODO: add TTL eviction\n"
                        "+\n"
                        "   public Ad getAd(AdRequest request) {\n"
                        "+    String key = request.getContextKey();\n"
                        "+    if (impressionCache.containsKey(key)) {\n"
                        "+      return impressionCache.get(key).getAd();\n"
                        "+    }\n"
                        "     Ad ad = db.fetchAd(request);\n"
                        "+    impressionCache.put(key, new AdImpression(ad));\n"
                        "     return ad;\n"
                    ),
                }
            ],
            _T60,
        ),
        # Red herring — productcatalogservice LRU cache, 5 min before
        _gh_push(
            "productcatalogservice",
            "perf: add LRU product cache to reduce catalog file reads",
            "b2c3d4e",
            [
                {
                    "filename": "src/productcatalogservice/server.go",
                    "status": "modified",
                    "additions": 10,
                    "deletions": 3,
                    "patch": (
                        "@@ -28,9 +28,16 @@ type server struct {\n"
                        "+  cache *lru.Cache\n"
                        "+}\n"
                        " func (s *server) GetProduct(ctx context.Context,\n"
                        "     req *pb.GetProductRequest) (*pb.Product, error) {\n"
                        "+  if p, ok := s.cache.Get(req.Id); ok {\n"
                        "+    return p.(*pb.Product), nil\n"
                        "+  }\n"
                    ),
                }
            ],
            _T5,
        ),
    ],
    "noise_events": {
        "productcatalogservice": [
            _noise_event("otel", "info_log",
                         "GetProduct cache hit rate 73% - LRU cache working correctly",
                         payload={"cache.hit_rate": 0.73}),
        ],
        "frontend": [
            _noise_event("otel", "warn_log",
                         "GetAds RPC failed: rpc error: code=Unavailable "
                         "desc=transport is closing (adservice restarting)",
                         payload={"grpc.status": "14", "retry_attempt": 2}),
        ],
    },
}


# ===========================================================================
# HARD SCENARIOS — silent failures, multi-service noise, misleading signals
# ===========================================================================

OB_HARD_001 = {
    "id": "ob_hard_001",
    "task_index": "task_7",
    "difficulty": "hard",
    "title": "recommendationservice deployed with wrong model artifact (silent wrong data)",
    "description": (
        "A deploy to recommendationservice swapped the model tag from prod-v2 "
        "to prod-v1 by mistake. The service starts fine and returns HTTP 200, "
        "but recommendation scores are from the 2022 model — irrelevant products. "
        "No service reports an error. frontend shows degraded recommendation "
        "widgets. productcatalogservice had a separate caching PR merged just "
        "2 minutes before the incident alert fires (red herring)."
    ),
    "topology": {
        "services": [
            "frontend", "recommendationservice", "productcatalogservice",
        ],
        "edges": [
            ("frontend", "recommendationservice"),
            ("frontend", "productcatalogservice"),
            ("recommendationservice", "productcatalogservice"),
        ],
    },
    "fault_injection": {
        "root_cause_service": "recommendationservice",
        "fault_type": "wrong_model_artifact",
        "silent": True,   # returns 200 with wrong data — no HTTP errors
        "error_message": (
            "WARN: loaded model artifact recommendations-model:prod-v1 "
            "(expected prod-v2) - recommendation_score avg=0.21 "
            "(baseline prod-v2 avg=0.74)"
        ),
        "status_code_http": "200",
        "propagates_to": [],  # no cascade — silent data quality issue
        "red_herring_services": ["productcatalogservice"],
    },
    "observed_service": "frontend",
    "fault_start_ts": _BASE_TS,
    "ground_truth": {
        "root_cause_component": "recommendationservice",
        "root_cause_reason": "wrong model artifact prod-v1 deployed instead of prod-v2 causing degraded recommendations",
    },
    "scoring_points": _scoring_points(
        "recommendationservice",
        "wrong model artifact prod-v1 deployed instead of prod-v2 causing degraded recommendations",
        _BASE_STR,
    ),
    "github_events": [
        # Root-cause deploy — 60 min before (less suspicious timing)
        _gh_push(
            "recommendationservice",
            "chore: update model artifact tag for June refresh",
            "cc1dd2ee",
            [
                {
                    "filename": "src/recommendationservice/requirements.txt",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 1,
                    "patch": (
                        "@@ -3,7 +3,7 @@ grpcio==1.59.0\n"
                        "-MODEL_ARTIFACT=recommendations-model:prod-v2\n"
                        "+MODEL_ARTIFACT=recommendations-model:prod-v1\n"
                    ),
                }
            ],
            _T60,
        ),
        # Red herring — productcatalogservice, merged 2 min before alert fires
        _gh_pr(
            "productcatalogservice",
            "perf: preload hot products into in-memory cache on startup",
            398,
            [
                {
                    "filename": "src/productcatalogservice/server.go",
                    "status": "modified",
                    "additions": 20,
                    "deletions": 4,
                    "patch": (
                        "@@ -34,10 +34,26 @@ func (s *server) init() error {\n"
                        "+  log.Printf(\"Preloading top-%d products into hot cache\", hotN)\n"
                        "+  products, err := s.parseCatalog()\n"
                        "+  if err != nil { return err }\n"
                        "+  for i, p := range products {\n"
                        "+    if i >= hotN { break }\n"
                        "+    s.hotCache.Set(p.Id, p)\n"
                        "+  }\n"
                    ),
                }
            ],
            _T2,
        ),
    ],
    "noise_events": {
        "productcatalogservice": [
            _noise_event("otel", "info_log",
                         "Preloaded 10 hot products into cache on startup",
                         payload={"cache.preloaded": 10}),
            _noise_event("otel", "info_log",
                         "GetProduct cache hit rate 81% - hot cache working",
                         payload={"cache.hit_rate": 0.81}),
        ],
        "frontend": [
            _noise_event("otel", "info_log",
                         "ListRecommendations returned 10 products (HTTP 200) in 43ms",
                         payload={"http.status_code": "200", "recommendation_count": 10}),
        ],
        "recommendationservice": [
            _noise_event("otel", "warn_log",
                         "WARN: loaded model artifact recommendations-model:prod-v1 "
                         "(expected prod-v2) - recommendation_score avg=0.21 (baseline prod-v2 avg=0.74)",
                         payload={"model.version": "prod-v1", "score.avg": 0.21}),
        ],
    },
}


OB_HARD_002 = {
    "id": "ob_hard_002",
    "task_index": "task_8",
    "difficulty": "hard",
    "title": "currencyservice falls back to stale hardcoded rates after Redis flush",
    "description": (
        "An ops flush of Redis cleared currencyservice's rate cache. When the "
        "external rate API also timed out (upstream issue), currencyservice fell "
        "back to hardcoded 2020 exchange rates. Prices displayed in GBP/EUR are "
        "40% off. All services return HTTP 200 — no observable error. "
        "frontend had a UI cosmetic deploy 5 min before the alert (red herring). "
        "checkoutservice had a minor config push 2 min before (red herring)."
    ),
    "topology": {
        "services": [
            "frontend", "currencyservice", "checkoutservice",
        ],
        "edges": [
            ("frontend", "currencyservice"),
            ("frontend", "checkoutservice"),
            ("checkoutservice", "currencyservice"),
        ],
    },
    "fault_injection": {
        "root_cause_service": "currencyservice",
        "fault_type": "stale_fallback_rates",
        "silent": True,
        "error_message": (
            "WARN: Redis cache miss for all rate keys (FLUSHALL detected), "
            "external API timeout after 5000ms - using hardcoded fallback rates "
            "from 2020-01-01 (may be significantly stale)"
        ),
        "status_code_http": "200",
        "propagates_to": [],
        "red_herring_services": ["frontend", "checkoutservice"],
    },
    "observed_service": "frontend",
    "fault_start_ts": _BASE_TS,
    "ground_truth": {
        "root_cause_component": "currencyservice",
        "root_cause_reason": "stale hardcoded fallback exchange rates used after Redis flush and external API timeout",
    },
    "scoring_points": _scoring_points(
        "currencyservice",
        "stale hardcoded fallback exchange rates used after Redis flush and external API timeout",
        _BASE_STR,
    ),
    "github_events": [
        # Red herring #1 — frontend UI cosmetic deploy 5 min before
        _gh_push(
            "frontend",
            "ui: update price display component to show currency symbol before amount",
            "11223344",
            [
                {
                    "filename": "src/frontend/templates/product.html",
                    "status": "modified",
                    "additions": 3,
                    "deletions": 3,
                    "patch": (
                        "@@ -44,9 +44,9 @@ <div class=\"product-price\">\n"
                        "-  {{ .Price }} {{ .CurrencyCode }}\n"
                        "+  {{ .CurrencyCode }} {{ .Price }}\n"
                    ),
                }
            ],
            _T5,
        ),
        # Red herring #2 — checkoutservice config push 2 min before
        _gh_push(
            "checkoutservice",
            "config: bump gRPC keepalive timeout from 30s to 60s",
            "aabbccdd",
            [
                {
                    "filename": "src/checkoutservice/main.go",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 1,
                    "patch": (
                        "@@ -28,7 +28,7 @@ func dialGRPC(addr string) (*grpc.ClientConn, error) {\n"
                        "-  grpc.WithKeepaliveParams(keepalive.ClientParameters{Timeout: 30 * time.Second}),\n"
                        "+  grpc.WithKeepaliveParams(keepalive.ClientParameters{Timeout: 60 * time.Second}),\n"
                    ),
                }
            ],
            _T2,
        ),
        # Root-cause: currencyservice fallback rate config — 60 min before (less obvious timing)
        _gh_push(
            "currencyservice",
            "chore: add hardcoded fallback rates for offline resilience",
            "55667788",
            [
                {
                    "filename": "src/currencyservice/server.js",
                    "status": "modified",
                    "additions": 12,
                    "deletions": 0,
                    "patch": (
                        "@@ -88,6 +88,18 @@ async function getRate(from, to) {\n"
                        "+  // Fallback: use hardcoded baseline rates if Redis miss AND API fails\n"
                        "+  if (!redisRate && apiError) {\n"
                        "+    logger.warn(\n"
                        "+      'Redis cache miss, external API timeout, using fallback rates (may be stale)');\n"
                        "+    return HARDCODED_RATES_2020[from]?.[to] ?? 1.0;\n"
                        "+  }\n"
                    ),
                }
            ],
            _T60,
        ),
    ],
    "noise_events": {
        "frontend": [
            _noise_event("otel", "info_log",
                         "Rendered product page with currency=GBP price=£38.50 (HTTP 200)",
                         payload={"http.status_code": "200", "currency": "GBP"}),
        ],
        "checkoutservice": [
            _noise_event("otel", "info_log",
                         "PlaceOrder succeeded - gRPC keepalive timeout=60s applied",
                         payload={"http.status_code": "200"}),
        ],
        "currencyservice": [
            _noise_event("otel", "warn_log",
                         "WARN: Redis cache miss for all rate keys (FLUSHALL detected), "
                         "external API timeout after 5000ms - using hardcoded fallback rates from 2020-01-01",
                         payload={"redis.miss": True, "api.timeout": True, "fallback": "2020-01-01"}),
        ],
    },
}


OB_HARD_003 = {
    "id": "ob_hard_003",
    "task_index": "task_9",
    "difficulty": "hard",
    "title": "checkoutservice idempotency key bug causes double charges on retries",
    "description": (
        "checkoutservice retries payment on transient network errors but reuses "
        "the same idempotency key, causing paymentservice to charge the customer "
        "twice. checkoutservice shows intermittent 500s (first attempt times out) "
        "followed by 200 (retry succeeds). paymentservice logs two successful "
        "ChargeResponse records per order. emailservice sends duplicate "
        "confirmation emails. "
        "paymentservice just received a new major version deploy 5 min before "
        "(looks very suspicious). The bug is actually in checkoutservice retry "
        "logic — a minor-looking patch."
    ),
    "topology": {
        "services": [
            "frontend", "checkoutservice",
            "paymentservice", "emailservice",
        ],
        "edges": [
            ("frontend", "checkoutservice"),
            ("checkoutservice", "paymentservice"),
            ("checkoutservice", "emailservice"),
        ],
    },
    "fault_injection": {
        "root_cause_service": "checkoutservice",
        "fault_type": "idempotency_key_reuse",
        "silent": False,
        "error_message": (
            "WARN: payment retry attempt 2 reusing idempotency_key=ck_ord_7f3a2b "
            "- original ChargeRequest may already have succeeded; "
            "possible duplicate charge for order_id=ORD-20240601-9821"
        ),
        "status_code_http": "500",
        "propagates_to": ["frontend"],
        "red_herring_services": ["paymentservice"],
    },
    "observed_service": "frontend",
    "fault_start_ts": _BASE_TS,
    "ground_truth": {
        "root_cause_component": "checkoutservice",
        "root_cause_reason": "idempotency key reused on payment retry causing duplicate charges",
    },
    "scoring_points": _scoring_points(
        "checkoutservice",
        "idempotency key reused on payment retry causing duplicate charges",
        _BASE_STR,
    ),
    "github_events": [
        # Red herring — paymentservice major version deploy 5 min before (very suspicious)
        _gh_push(
            "paymentservice",
            "feat: upgrade payment provider SDK to v3 with 3DS support",
            "99aabbcc",
            [
                {
                    "filename": "src/paymentservice/package.json",
                    "status": "modified",
                    "additions": 2,
                    "deletions": 2,
                    "patch": (
                        "@@ -12,8 +12,8 @@ {\n"
                        "-  \"stripe\": \"^8.0.0\",\n"
                        "+  \"stripe\": \"^13.0.0\",\n"
                        "-  \"@google/payment-provider\": \"2.1.4\"\n"
                        "+  \"@google/payment-provider\": \"3.0.1\"\n"
                    ),
                },
                {
                    "filename": "src/paymentservice/charge.js",
                    "status": "modified",
                    "additions": 15,
                    "deletions": 9,
                    "patch": (
                        "@@ -22,15 +22,21 @@ async function charge(amount, creditCard) {\n"
                        "-  const result = await stripe.charges.create({...});\n"
                        "+  // v3: use PaymentIntents API\n"
                        "+  const intent = await stripe.paymentIntents.create({\n"
                        "+    amount: toCents(amount),\n"
                        "+    currency: amount.currency_code.toLowerCase(),\n"
                        "+    payment_method: tokenizeCard(creditCard),\n"
                        "+    confirm: true,\n"
                        "+  });\n"
                    ),
                },
            ],
            _T5,
        ),
        # Root cause — checkoutservice minor-looking patch 15 min before
        _gh_push(
            "checkoutservice",
            "fix: simplify payment retry logic to reduce code complexity",
            "dd11ee22",
            [
                {
                    "filename": "src/checkoutservice/main.go",
                    "status": "modified",
                    "additions": 5,
                    "deletions": 8,
                    "patch": (
                        "@@ -112,14 +112,11 @@ func (cs *checkoutService) PlaceOrder(\n"
                        "   idempotencyKey := generateIdempotencyKey(req)\n"
                        "-  for attempt := 0; attempt < maxRetries; attempt++ {\n"
                        "-    // Regenerate key on each attempt to prevent duplicate charges\n"
                        "-    if attempt > 0 {\n"
                        "-      idempotencyKey = generateIdempotencyKey(req) + \n"
                        "-          fmt.Sprintf(\"-retry-%d\", attempt)\n"
                        "-    }\n"
                        "-    err = cs.chargeCard(ctx, idempotencyKey, amount, card)\n"
                        "+  for attempt := 0; attempt < maxRetries; attempt++ {\n"
                        "+    // Simplified: reuse key for cleaner logs\n"
                        "+    err = cs.chargeCard(ctx, idempotencyKey, amount, card)\n"
                        "     if err == nil { break }\n"
                        "   }\n"
                    ),
                }
            ],
            _T15,
        ),
    ],
    "noise_events": {
        "paymentservice": [
            _noise_event("otel", "info_log",
                         "ChargeCard succeeded with stripe v3 PaymentIntents API (HTTP 200)",
                         payload={"http.status_code": "200", "stripe.version": "v3"}),
            _noise_event("otel", "info_log",
                         "ChargeCard succeeded (duplicate idempotency_key=ck_ord_7f3a2b accepted by provider)",
                         payload={"http.status_code": "200", "idempotency_key": "ck_ord_7f3a2b"}),
        ],
        "emailservice": [
            _noise_event("otel", "warn_log",
                         "WARN: SendOrderConfirmation called twice for order_id=ORD-20240601-9821 "
                         "within 12s - possible duplicate order event",
                         payload={"order_id": "ORD-20240601-9821", "duplicate": True}),
        ],
    },
}


OB_HARD_004 = {
    "id": "ob_hard_004",
    "task_index": "task_10",
    "difficulty": "hard",
    "title": "productcatalogservice slow variant lookup degrades recommendations silently",
    "description": (
        "productcatalogservice introduced a regression that performs an unindexed "
        "scan over product variants when n_variants > 20. recommendationservice "
        "calls GetProduct for enrichment and times out on popular items, returning "
        "partial recommendations with HTTP 200. frontend shows incomplete product "
        "grids for some users with no error shown. "
        "recommendationservice just had a scoring algorithm deploy 2 min before "
        "the alert (very suspicious red herring). frontend had a cosmetic change "
        "merged 5 min earlier (another red herring). The actual root cause — "
        "productcatalogservice variant scan — was deployed 30 min ago and is "
        "buried in a 400-line diff."
    ),
    "topology": {
        "services": [
            "frontend", "recommendationservice",
            "productcatalogservice", "checkoutservice",
        ],
        "edges": [
            ("frontend", "recommendationservice"),
            ("frontend", "productcatalogservice"),
            ("frontend", "checkoutservice"),
            ("recommendationservice", "productcatalogservice"),
            ("checkoutservice", "productcatalogservice"),
        ],
    },
    "fault_injection": {
        "root_cause_service": "productcatalogservice",
        "fault_type": "slow_variant_lookup",
        "silent": True,   # returns partial 200 responses, no HTTP error at root
        "error_message": (
            "WARN: ListProductsByCategory took 4521ms for product_id=OLJCESPC7Z "
            "(n_variants=47) - full table scan on variants (missing index on category_id)"
        ),
        "status_code_http": "200",
        "propagates_to": [],
        "red_herring_services": ["recommendationservice", "frontend"],
    },
    "observed_service": "frontend",
    "fault_start_ts": _BASE_TS,
    "ground_truth": {
        "root_cause_component": "productcatalogservice",
        "root_cause_reason": "unindexed variant table scan causing slow GetProduct responses and partial recommendation data",
    },
    "scoring_points": _scoring_points(
        "productcatalogservice",
        "unindexed variant table scan causing slow GetProduct responses and partial recommendation data",
        _BASE_STR,
    ),
    "github_events": [
        # Red herring #1 — recommendationservice scoring algo, 2 min before (very suspicious)
        _gh_push(
            "recommendationservice",
            "feat: switch from collaborative to hybrid scoring model for better CTR",
            "ff001122",
            [
                {
                    "filename": "src/recommendationservice/recommendation_server.py",
                    "status": "modified",
                    "additions": 31,
                    "deletions": 12,
                    "patch": (
                        "@@ -67,18 +67,37 @@ class RecommendationService:\n"
                        "-  def _score(self, user_id, products):\n"
                        "-    return collaborative_filter(user_id, products)\n"
                        "+  def _score(self, user_id, products):\n"
                        "+    cf_scores = collaborative_filter(user_id, products)\n"
                        "+    cb_scores = content_based_filter(products)\n"
                        "+    return hybrid_blend(cf_scores, cb_scores, alpha=0.6)\n"
                    ),
                }
            ],
            _T2,
        ),
        # Red herring #2 — frontend cosmetic, 5 min before
        _gh_push(
            "frontend",
            "ui: add skeleton loader for recommendation widget",
            "33445566",
            [
                {
                    "filename": "src/frontend/static/js/recommendations.js",
                    "status": "modified",
                    "additions": 8,
                    "deletions": 2,
                    "patch": (
                        "@@ -14,8 +14,14 @@ function loadRecommendations(container) {\n"
                        "+  showSkeletonLoader(container);\n"
                        "   fetch('/recommendations').then(resp => {\n"
                        "+    hideSkeletonLoader(container);\n"
                        "     renderProducts(container, resp.products);\n"
                        "   });\n"
                    ),
                }
            ],
            _T5,
        ),
        # Root cause — productcatalogservice, 30 min before, buried in large diff
        _gh_push(
            "productcatalogservice",
            "refactor: restructure product variant storage for extensibility (400-line cleanup)",
            "77889900",
            [
                {
                    "filename": "src/productcatalogservice/server.go",
                    "status": "modified",
                    "additions": 387,
                    "deletions": 198,
                    "patch": (
                        "@@ -201,14 +201,19 @@ func (s *server) ListProducts(\n"
                        "   // ... (350 lines of refactoring above) ...\n"
                        "-  rows, err := db.Query(\n"
                        "-    `SELECT * FROM products p JOIN variants v \n"
                        "-     ON p.id = v.product_id WHERE p.category_id = $1\n"
                        "-     AND v.available = true`, categoryID)\n"
                        "+  // Restructured: scan variants table directly for flexibility\n"
                        "+  rows, err := db.Query(\n"
                        "+    `SELECT * FROM variants v JOIN products p \n"
                        "+     ON v.product_id = p.id WHERE v.category_id = $1\n"
                        "+     AND v.available = true`, categoryID)\n"
                        "+  // Note: variants.category_id index was dropped in migration 042\n"
                    ),
                },
                {
                    "filename": "src/productcatalogservice/migrations/042_restructure_variants.sql",
                    "status": "added",
                    "additions": 12,
                    "deletions": 0,
                    "patch": (
                        "@@ -0,0 +1,12 @@\n"
                        "+-- Migration 042: restructure variants table\n"
                        "+ALTER TABLE variants ADD COLUMN category_id INT;\n"
                        "+UPDATE variants v SET category_id = (\n"
                        "+    SELECT category_id FROM products WHERE id = v.product_id);\n"
                        "+-- TODO: add index on category_id after backfill\n"
                        "+DROP INDEX IF EXISTS idx_products_category_id;\n"
                    ),
                },
            ],
            _T30,
        ),
    ],
    "noise_events": {
        "recommendationservice": [
            _noise_event("otel", "warn_log",
                         "GetProduct enrichment timeout for product_id=OLJCESPC7Z after 5000ms "
                         "- returning partial recommendation data (3/10 products enriched)",
                         payload={"product_id": "OLJCESPC7Z", "enriched": 3, "total": 10}),
            _noise_event("otel", "info_log",
                         "Hybrid scoring model loaded: alpha=0.6, cf_weight=0.6, cb_weight=0.4",
                         payload={"model": "hybrid", "alpha": 0.6}),
        ],
        "frontend": [
            _noise_event("otel", "info_log",
                         "Skeleton loader rendered for recommendation widget "
                         "(3 of 10 products loaded, partial response from recommendationservice)",
                         payload={"loaded": 3, "total": 10}),
        ],
        "checkoutservice": [
            _noise_event("otel", "info_log",
                         "GetProduct for checkout completed in 78ms - no issues",
                         payload={"http.status_code": "200"}),
        ],
    },
}


# ===========================================================================
# Master list
# ===========================================================================

OB_SCENARIOS = [
    OB_EASY_001,
    OB_EASY_002,
    OB_EASY_003,
    OB_MEDIUM_001,
    OB_MEDIUM_002,
    OB_MEDIUM_003,
    OB_HARD_001,
    OB_HARD_002,
    OB_HARD_003,
    OB_HARD_004,
]
