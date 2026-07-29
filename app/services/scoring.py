def calculate_hotel_scores(hotels: list, weights: dict, max_budget: float, desired_amenities: list = None) -> list:
    scored_hotels = []

    w_price = weights.get('price', 0.25)
    w_rating = weights.get('rating', 0.25)
    w_distance = weights.get('distance', 0.25)
    w_amenities = weights.get('amenities', 0.25)

    desired = [a.lower() for a in (desired_amenities or [])]

    for hotel in hotels:
        # Normalize Price: 1.0 is free, 0.0 is over budget
        n_price = max(0.0, 1.0 - (hotel['price'] / max_budget)) if max_budget else 0.5

        # Normalize Rating: 5.0 -> 1.0
        n_rating = hotel['rating'] / 5.0

        # Normalize Distance: closer is better (assuming max acceptable distance is 20km)
        n_distance = max(0.0, 1.0 - (hotel['distance_km'] / 20.0))

        # Normalize Amenities: proporsi fasilitas yang diinginkan user yang dimiliki hotel ini.
        # Kalau user tidak menyebut fasilitas spesifik, ATAU data hotel ini tidak menyertakan
        # info fasilitas sama sekali (mis. hasil live dari MakCorps yang belum tahu fasilitasnya),
        # anggap netral (1.0) supaya tidak dihukum karena ketidaktahuan data, bukan karena
        # benar-benar tidak punya fasilitas tsb.
        if desired and 'amenities' in hotel:
            hotel_amenities = set(a.lower() for a in hotel.get('amenities', []))
            n_amenities = len(hotel_amenities & set(desired)) / len(desired)
        else:
            n_amenities = 1.0

        final_score = (w_price * n_price) + (w_rating * n_rating) + (w_distance * n_distance) + (w_amenities * n_amenities)

        # Sedikit bonus untuk hotel yang sedang promo/deal, supaya cenderung muncul
        # lebih atas - tapi tidak mendominasi skor (cuma 5%), jadi hotel promo yang
        # harganya kemahalan/rating jelek tidak otomatis jadi rekomendasi #1.
        if hotel.get("deal"):
            final_score += 0.05

        hotel['final_score'] = round(final_score, 4)
        scored_hotels.append(hotel)

    # Sort descending by score
    return sorted(scored_hotels, key=lambda x: x['final_score'], reverse=True)
