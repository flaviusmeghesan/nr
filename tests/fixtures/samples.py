"""Raspunsuri JSON imitand formele reale pe care le trimit platformele.

Sunt scrise de mana dupa structurile publice cunoscute si sunt folosite ca sa
testam extractia fara retea. Variantele "vechi"/"noi" din acelasi fisier
verifica exact ce ne intereseaza: ca extractia merge si daca platforma isi
schimba forma raspunsului.
"""

# Instagram - varianta moderna (API v1 / xdt GraphQL), imbracata adanc
INSTAGRAM_MODERN = {
    "data": {
        "xdt_api__v1__feed__user_timeline_graphql_connection": {
            "edges": [
                {"node": {
                    "pk": "3456789012345678901",
                    "id": "3456789012345678901_1234567",
                    "code": "C9xAbCdEfGh",
                    "taken_at": 1789056000,
                    "media_type": 2,
                    "product_type": "clips",
                    "caption": {"text": "Burger nou in meniu!\nVino azi."},
                    "like_count": 245,
                    "comment_count": 18,
                    "play_count": 5300,
                    "image_versions2": {"candidates": [{"url": "https://cdn/ig1.jpg"}]},
                }},
                {"node": {
                    "pk": "3456789012345678902",
                    "code": "C9xAbCdEfGi",
                    "taken_at": 1788969600,
                    "media_type": 8,
                    "caption": {"text": "Galerie din bucatarie"},
                    "like_count": 120,
                    "comment_count": 4,
                    "image_versions2": {"candidates": [{"url": "https://cdn/ig2.jpg"}]},
                }},
            ]
        }
    }
}

# Instagram - varianta veche (edge_owner_to_timeline_media), alte denumiri
INSTAGRAM_LEGACY = {
    "data": {"user": {"edge_owner_to_timeline_media": {"edges": [
        {"node": {
            "id": "3456789012345678903",
            "shortcode": "C9xAbCdEfGj",
            "taken_at_timestamp": 1788883200,
            "is_video": False,
            "__typename": "GraphImage",
            "edge_media_to_caption": {"edges": [{"node": {"text": "Poza cu terasa"}}]},
            "edge_liked_by": {"count": 88},
            "edge_media_to_comment": {"count": 3},
            "display_url": "https://cdn/ig3.jpg",
        }},
    ]}}}
}

# TikTok - din __UNIVERSAL_DATA_FOR_REHYDRATION__ sau /api/post/item_list/
TIKTOK_ITEM_LIST = {
    "itemList": [
        {
            "id": "7412345678901234567",
            "desc": "Cum facem burgerul #food",
            "createTime": 1789056000,
            "author": {"uniqueId": "restaurantcentral"},
            "stats": {"playCount": 15200, "diggCount": 890,
                      "commentCount": 45, "shareCount": 23},
            "video": {"cover": "https://cdn/tt1.jpg", "duration": 32},
        },
        {
            "id": "7412345678901234568",
            "desc": "Din bucatarie",
            "createTime": 1788969600,
            "author": {"uniqueId": "restaurantcentral"},
            "stats": {"playCount": 4300, "diggCount": 210,
                      "commentCount": 9, "shareCount": 4},
            "video": {"cover": "https://cdn/tt2.jpg"},
        },
    ]
}

# Facebook - forma GraphQL de pe pagina
FACEBOOK_FEED = {
    "data": {"node": {"timeline_list_feed_units": {"edges": [
        {"node": {
            "post_id": "1122334455667788",
            "creation_time": 1789056000,
            "message": {"text": "Meniul zilei e live pe site."},
            "wwwURL": "https://www.facebook.com/restaurantcentral/posts/1122334455667788",
            "attachments": [{"media": {"__typename": "Photo",
                                       "image": {"uri": "https://cdn/fb1.jpg"}}}],
            "feedback": {"reaction_count": {"count": 64},
                         "comment_count": {"total_count": 12},
                         "share_count": {"count": 5}},
        }},
    ]}}}
}

# Raspuns fara nicio postare - trebuie sa iasa lista goala, nu eroare
NOISE = {"data": {"viewer": {"actor": {"id": "123"}}}, "extensions": {"is_final": True}}
