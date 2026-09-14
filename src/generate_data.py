import numpy as np
import pandas as pd
from datetime import date, timedelta


# ============================================================
# CONFIGURATION
# ============================================================

SEED = 532

N_DAYS = 365
INTERVAL_MINUTES = 1

START_DATE = date(2026, 1, 1)

OUTPUT_FILE = "dataset.csv"


# ------------------------------------------------------------
# Infrastructure
# ------------------------------------------------------------

BASE_CAPACITY_PODS = 5
POD_CAPACITY_RPM = 180

MIN_PODS = 5
MAX_PODS = 30

SCALE_UP_THRESHOLD = 0.85
SCALE_DOWN_THRESHOLD = 0.40

POD_BOOT_DELAY_STEPS = 3
SCALE_COOLDOWN_STEPS = 6


# ------------------------------------------------------------
# Cloud pricing
# ------------------------------------------------------------

SPOT_FRACTION = 0.60

SPOT_COST = 0.08
ONDEMAND_COST = 0.20

SPOT_PREEMPTION_PROB = 0.01


# ------------------------------------------------------------
# Demand growth
# ------------------------------------------------------------

GROWTH_RATE_PER_DAY = 0.001


# ------------------------------------------------------------
# Seasonal effect
# ------------------------------------------------------------

HOLIDAY_SEASON_MONTHS = (10, 11)
HOLIDAY_SEASON_BOOST = 1.35


# ============================================================
# INDIAN HOLIDAYS / FESTIVALS
# ============================================================
#
# multiplier = additional demand caused by the event
#
# Example:
#
# normal demand = 1000
# multiplier = 1.8
# holiday demand ≈ 1800
#
# ============================================================

INDIA_HOLIDAYS_2026 = {

    date(2026, 1, 26):
        ("Republic Day", 1.15),

    date(2026, 3, 4):
        ("Holi", 1.80),

    date(2026, 3, 21):
        ("Id-ul-Fitr", 1.60),

    date(2026, 3, 26):
        ("Ram Navami", 1.30),

    date(2026, 3, 31):
        ("Mahavir Jayanti", 1.20),

    date(2026, 4, 3):
        ("Good Friday", 1.20),

    date(2026, 5, 1):
        ("Buddha Purnima", 1.20),

    date(2026, 5, 27):
        ("Bakrid", 1.50),

    date(2026, 6, 26):
        ("Muharram", 1.20),

    date(2026, 8, 15):
        ("Independence Day", 1.30),

    date(2026, 8, 26):
        ("Milad-un-Nabi", 1.20),

    date(2026, 9, 4):
        ("Janmashtami", 1.40),

    date(2026, 10, 2):
        ("Gandhi Jayanti", 1.20),

    date(2026, 10, 20):
        ("Dussehra", 1.60),

    date(2026, 11, 8):
        ("Diwali", 2.00),

    date(2026, 11, 24):
        ("Guru Nanak Jayanti", 1.30),

    date(2026, 12, 25):
        ("Christmas", 1.50),
}


# ============================================================
# RANDOM DAY EVENTS
# ============================================================

def generate_day_events(n_days, rng):

    events = []

    for day_index in range(n_days):

        current_date = START_DATE + timedelta(days=day_index)

        # ----------------------------------------------------
        # First check actual calendar holiday
        # ----------------------------------------------------

        if current_date in INDIA_HOLIDAYS_2026:

            holiday_name, holiday_multiplier = INDIA_HOLIDAYS_2026[
                current_date
            ]

            events.append({
                "day_type": "festival",
                "weather": "clear",
                "holiday_name": holiday_name,
                "is_holiday": 1,
                "holiday_multiplier": holiday_multiplier,
            })

            continue

        # ----------------------------------------------------
        # Random weather
        # ----------------------------------------------------

        rain_probability = 0.12

        is_rain = rng.random() < rain_probability

        # ----------------------------------------------------
        # Random festival-like event
        #
        # This is separate from official holidays.
        # Think local events / special demand days.
        # ----------------------------------------------------

        random_festival = rng.random() < 0.03

        if random_festival:

            events.append({
                "day_type": "festival",
                "weather": "rain" if is_rain else "clear",
                "holiday_name": "Local Festival",
                "is_holiday": 0,
                "holiday_multiplier": rng.uniform(1.4, 1.8),
            })

        elif is_rain:

            events.append({
                "day_type": "rain",
                "weather": "rain",
                "holiday_name": None,
                "is_holiday": 0,
                "holiday_multiplier": 1.0,
            })

        else:

            events.append({
                "day_type": "normal",
                "weather": "clear",
                "holiday_name": None,
                "is_holiday": 0,
                "holiday_multiplier": 1.0,
            })

    return events


# ============================================================
# DEMAND CURVE
# ============================================================

def gaussian_peak(hour, center, width, height):

    return height * np.exp(
        -((hour - center) ** 2) /
        (2 * width ** 2)
    )


def daily_demand_curve(hour, is_weekend):

    if not is_weekend:

        # Weekday:
        #
        # morning
        # lunch
        # evening
        #

        base = (
            400
            + gaussian_peak(hour, 8.5, 0.8, 900)
            + gaussian_peak(hour, 12.5, 0.9, 700)
            + gaussian_peak(hour, 19.5, 1.2, 1200)
        )

    else:

        # Weekend:
        #
        # people wake later
        # lunch shifts later
        # evening remains strong
        #

        base = (
            500
            + gaussian_peak(hour, 11.5, 1.5, 700)
            + gaussian_peak(hour, 20.0, 1.5, 1100)
        )

    return base


# ============================================================
# AUTOCORRELATED DEMAND NOISE
# ============================================================

def update_ar_noise(previous_noise, rng):

    # Persistent noise.
    #
    # If demand suddenly increases,
    # the effect does not disappear immediately.
    #

    new_noise = (
        0.90 * previous_noise
        + rng.normal(0, 30)
    )

    return new_noise


# ============================================================
# PROMOTION GENERATOR
# ============================================================

def maybe_start_promotion(
    step,
    promo_active_until,
    promo_magnitude,
    steps_per_day,
    rng
):

    # Already running
    if step <= promo_active_until:

        return promo_active_until, promo_magnitude

    # Small probability of a promotion starting
    #
    # Roughly a few promotions per month
    #

    if rng.random() < (0.03 / steps_per_day):

        duration = rng.integers(
            30,
            180
        )

        magnitude = rng.uniform(
            400,
            1400
        )

        promo_active_until = step + duration

        promo_magnitude = magnitude

    else:

        promo_active_until = -1
        promo_magnitude = 0

    return promo_active_until, promo_magnitude


# ============================================================
# MAIN TELEMETRY GENERATOR
# ============================================================

def generate_telemetry(
    n_days=N_DAYS,
    interval_minutes=INTERVAL_MINUTES,
    seed=SEED
):

    rng = np.random.default_rng(seed)

    steps_per_day = int(
        24 * 60 / interval_minutes
    )

    total_steps = (
        n_days * steps_per_day
    )

    # --------------------------------------------------------
    # Generate daily events first
    # --------------------------------------------------------

    day_events = generate_day_events(
        n_days,
        rng
    )

    # --------------------------------------------------------
    # Infrastructure state
    # --------------------------------------------------------

    active_pods = BASE_CAPACITY_PODS

    pods_booting = []

    last_scale_step = -999999

    # --------------------------------------------------------
    # Demand state
    # --------------------------------------------------------

    ar_noise = 0.0

    promo_active_until = -1
    promo_magnitude = 0

    records = []

    # ========================================================
    # TIME LOOP
    # ========================================================

    for step in range(total_steps):

        # ----------------------------------------------------
        # Calendar
        # ----------------------------------------------------

        day_index = step // steps_per_day

        step_in_day = (
            step % steps_per_day
        )

        current_date = (
            START_DATE
            + timedelta(days=day_index)
        )

        hour = (
            step_in_day
            * interval_minutes
            / 60.0
        )

        day_of_week = current_date.weekday()

        is_weekend = day_of_week >= 5

        month = current_date.month

        # ----------------------------------------------------
        # Event information
        # ----------------------------------------------------

        event = day_events[day_index]

        day_type = event["day_type"]

        weather = event["weather"]

        holiday_name = event["holiday_name"]

        is_holiday = event["is_holiday"]

        holiday_multiplier = event[
            "holiday_multiplier"
        ]

        # ====================================================
        # BASE DEMAND
        # ====================================================

        base_demand = daily_demand_curve(
            hour,
            is_weekend
        )

        # ====================================================
        # HOLIDAY / FESTIVAL EFFECT
        # ====================================================

        #
        # IMPORTANT:
        #
        # The holiday information now ACTUALLY changes
        # the request rate.
        #

        base_demand *= holiday_multiplier

        # ====================================================
        # RAIN EFFECT
        # ====================================================

        if weather == "rain":

            # Rain increases delivery demand,
            # especially around meal times.
            #

            meal_effect = (
                gaussian_peak(
                    hour,
                    8.5,
                    1.0,
                    1
                )
                + gaussian_peak(
                    hour,
                    13.0,
                    1.2,
                    1
                )
                + gaussian_peak(
                    hour,
                    19.5,
                    1.5,
                    1
                )
            )

            rain_multiplier = (
                1
                + 0.35 * meal_effect
            )

            base_demand *= rain_multiplier

        # ====================================================
        # FESTIVAL SEASON
        # ====================================================

        if month in HOLIDAY_SEASON_MONTHS:

            base_demand *= HOLIDAY_SEASON_BOOST

        # ====================================================
        # LONG TERM BUSINESS GROWTH
        # ====================================================

        growth_multiplier = (
            (1 + GROWTH_RATE_PER_DAY)
            ** day_index
        )

        base_demand *= growth_multiplier

        # ====================================================
        # AUTOCORRELATED NOISE
        # ====================================================

        ar_noise = update_ar_noise(
            ar_noise,
            rng
        )

        # ====================================================
        # PROMOTION
        # ====================================================

        (
            promo_active_until,
            promo_magnitude
        ) = maybe_start_promotion(
            step,
            promo_active_until,
            promo_magnitude,
            steps_per_day,
            rng
        )

        if step <= promo_active_until:

            promo_boost = promo_magnitude

            promo_active = 1

        else:

            promo_boost = 0

            promo_active = 0

        # ====================================================
        # FINAL REQUEST RATE
        # ====================================================

        request_rate = (
            base_demand
            + ar_noise
            + promo_boost
        )

        # Small measurement noise
        request_rate += rng.normal(0, 8)

        request_rate = max(
            50,
            request_rate
        )

        # ====================================================
        # CURRENT CAPACITY
        # ====================================================

        current_capacity_rpm = (
            active_pods
            * POD_CAPACITY_RPM
        )

        utilization_ratio = (
            request_rate
            / current_capacity_rpm
        )

        # ====================================================
        # SCALING DECISION
        # ====================================================

        can_scale = (
            step - last_scale_step
            >= SCALE_COOLDOWN_STEPS
        )

        if (
            can_scale
            and utilization_ratio
            > SCALE_UP_THRESHOLD
            and active_pods < MAX_PODS
        ):

            # Pod requested but not immediately available
            pods_booting.append(
                POD_BOOT_DELAY_STEPS
            )

            last_scale_step = step

        elif (
            can_scale
            and utilization_ratio
            < SCALE_DOWN_THRESHOLD
            and active_pods > MIN_PODS
        ):

            active_pods -= 1

            last_scale_step = step

        # ====================================================
        # POD BOOT PROCESS
        # ====================================================

        still_booting = []

        for remaining in pods_booting:

            remaining -= 1

            if remaining <= 0:

                active_pods += 1

            else:

                still_booting.append(
                    remaining
                )

        pods_booting = still_booting

        # ====================================================
        # SPOT INSTANCES
        # ====================================================

        scalable_pods = max(
            0,
            active_pods - BASE_CAPACITY_PODS
        )

        spot_pods = min(
            scalable_pods,
            int(
                scalable_pods
                * SPOT_FRACTION
            )
        )

        ondemand_pods = (
            active_pods
            - spot_pods
        )

        # ====================================================
        # SPOT PREEMPTION
        # ====================================================

        preemption_event = 0

        if (
            spot_pods > 0
            and rng.random()
            < SPOT_PREEMPTION_PROB
        ):

            preemption_event = 1

            active_pods = max(
                BASE_CAPACITY_PODS,
                active_pods - 1
            )

            # Recalculate after preemption
            scalable_pods = max(
                0,
                active_pods
                - BASE_CAPACITY_PODS
            )

            spot_pods = min(
                scalable_pods,
                int(
                    scalable_pods
                    * SPOT_FRACTION
                )
            )

            ondemand_pods = (
                active_pods
                - spot_pods
            )

        # ====================================================
        # ACTUAL CAPACITY AFTER SCALING/PREEMPTION
        # ====================================================

        current_capacity_rpm = (
            active_pods
            * POD_CAPACITY_RPM
        )

        utilization_ratio = (
            request_rate
            / current_capacity_rpm
        )

        # ====================================================
        # CPU
        # ====================================================

        cpu_utilization = (
            utilization_ratio
            * rng.uniform(
                0.90,
                1.05
            )
        )

        cpu_utilization = np.clip(
            cpu_utilization,
            0,
            1
        )

        # ====================================================
        # MEMORY
        # ====================================================

        memory_utilization = (
            utilization_ratio
            * rng.uniform(
                0.80,
                1.00
            )
        )

        memory_utilization = np.clip(
            memory_utilization,
            0,
            1
        )

        # ====================================================
        # QUEUE
        # ====================================================

        if request_rate > current_capacity_rpm:

            queue_length = int(
                (
                    request_rate
                    - current_capacity_rpm
                ) / 10
            )

        else:

            queue_length = 0

        # ====================================================
        # LATENCY + ERROR RATE
        # ====================================================

        if utilization_ratio <= 0.80:

            p95_latency_ms = (
                80
                + utilization_ratio * 60
                + rng.normal(0, 4)
            )

            error_rate = max(
                0,
                0.0005
                + rng.normal(
                    0,
                    0.0001
                )
            )

        else:

            overload = (
                utilization_ratio
                - 0.80
            )

            p95_latency_ms = (
                80
                + 0.8 * 60
                + (overload ** 2)
                * 4000
                + rng.normal(0, 15)
            )

            error_rate = (
                0.001
                + (overload ** 2)
                * 3
            )

            error_rate = min(
                0.5,
                max(
                    0,
                    error_rate
                )
            )

        p95_latency_ms = max(
            0,
            p95_latency_ms
        )

        # ====================================================
        # COST
        # ====================================================

        cost_per_hour = (
            spot_pods * SPOT_COST
            + ondemand_pods * ONDEMAND_COST
        )

        # ====================================================
        # STORE RECORD
        # ====================================================

        records.append({

            # -------------------------
            # Time
            # -------------------------

            "timestamp": (
                current_date.isoformat()
                + " "
                + f"{int(hour):02d}:"
                + f"{int((hour % 1) * 60):02d}:00"
            ),

            "day": day_index,

            "date": current_date.isoformat(),

            "day_of_week": day_of_week,

            "time_of_day": round(
                hour,
                3
            ),

            # -------------------------
            # External demand factors
            # -------------------------

            "day_type": day_type,

            "weather": weather,

            "is_holiday": is_holiday,

            "holiday_name": (
                holiday_name
                if holiday_name is not None
                else "None"
            ),

            "promo_active": promo_active,

            # -------------------------
            # Demand
            # -------------------------

            "request_rate": round(
                request_rate,
                2
            ),

            # -------------------------
            # Infrastructure
            # -------------------------

            "active_pods": active_pods,

            "pods_booting": len(
                pods_booting
            ),

            "spot_pods": spot_pods,

            "ondemand_pods": ondemand_pods,

            "preemption_event":
                preemption_event,

            # -------------------------
            # Resource utilization
            # -------------------------

            "cpu_utilization": round(
                cpu_utilization,
                4
            ),

            "memory_utilization": round(
                memory_utilization,
                4
            ),

            # -------------------------
            # Performance
            # -------------------------

            "queue_length":
                queue_length,

            "p95_latency_ms": round(
                p95_latency_ms,
                2
            ),

            "error_rate": round(
                error_rate,
                5
            ),

            # -------------------------
            # Cost
            # -------------------------

            "cost_per_hour": round(
                cost_per_hour,
                3
            ),
        })

    return pd.DataFrame(records)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    df = generate_telemetry()

    df.to_csv(
        OUTPUT_FILE,
        index=False
    )

    print(
        f"Saved {len(df):,} rows "
        f"to {OUTPUT_FILE}"
    )

    print("\nDataset shape:")
    print(df.shape)

    print("\nColumns:")
    print(df.columns.tolist())

    print("\nDay types:")
    print(
        df["day_type"]
        .value_counts()
    )

    print("\nHolidays:")
    print(
        df[df["is_holiday"] == 1][
            [
                "date",
                "holiday_name",
                "request_rate"
            ]
        ].drop_duplicates()
    )