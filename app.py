import os
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env before anything else
from flask import Flask, render_template, request, jsonify, session
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from datetime import datetime, timedelta
import hashlib
import json
import time
import random
from collections import Counter, defaultdict
import re
from functools import wraps
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')

# Configuration

class Config:
    # Configuration
    SPOTIPY_CLIENT_ID = os.environ.get("SPOTIPY_CLIENT_ID")
    SPOTIPY_CLIENT_SECRET = os.environ.get("SPOTIPY_CLIENT_SECRET")
    RATE_LIMIT_REQUESTS = 50
    RATE_LIMIT_WINDOW = 3600  # 1 hour

# Initialize Spotify client with error handling and clear error for missing credentials
sp = None
if not Config.SPOTIPY_CLIENT_ID or not Config.SPOTIPY_CLIENT_SECRET:
    logger.error("SPOTIPY_CLIENT_ID or SPOTIPY_CLIENT_SECRET is missing. Please check your .env file.")
else:
    try:
        client_credentials_manager = SpotifyClientCredentials(
            client_id=Config.SPOTIPY_CLIENT_ID,
            client_secret=Config.SPOTIPY_CLIENT_SECRET
        )
        sp = spotipy.Spotify(client_credentials_manager=client_credentials_manager)
        logger.info("Spotify client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Spotify client: {e}")
        sp = None

# In-memory storage (production would use Redis/PostgreSQL)
user_sessions = {}
search_analytics = defaultdict(int)
music_insights_cache = {}
rate_limit_tracker = defaultdict(list)
user_preferences = {
    'liked_artists': set(),      # Artists the user liked (IDs only)
    'liked_artists_data': [],    # Complete artist data with names, images, etc.
    'saved_albums': [],          # Albums the user saved
    'genre_preferences': defaultdict(int),
    'listening_history': []
}

def rate_limit(max_requests=50, window=3600):
    """Rate limiting decorator"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            client_ip = request.remote_addr
            now = time.time()
            
            # Clean old requests
            rate_limit_tracker[client_ip] = [
                timestamp for timestamp in rate_limit_tracker[client_ip]
                if now - timestamp < window
            ]
            
            # Check rate limit
            if len(rate_limit_tracker[client_ip]) >= max_requests:
                return jsonify({
                    'error': 'Rate limit exceeded. Try again later.',
                    'retry_after': window - (now - rate_limit_tracker[client_ip][0])
                }), 429
            
            # Record this request
            rate_limit_tracker[client_ip].append(now)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

class MusicIntelligenceEngine:
    """Advanced music analysis and recommendation system"""
    
    def __init__(self):
        self.mood_profiles = {
            'energetic_happy': {'energy': (0.7, 1.0), 'valence': (0.7, 1.0)},
            'chill_positive': {'energy': (0.0, 0.4), 'valence': (0.6, 1.0)},
            'intense_dark': {'energy': (0.7, 1.0), 'valence': (0.0, 0.3)},
            'melancholic': {'energy': (0.0, 0.4), 'valence': (0.0, 0.4)},
            'dance_party': {'danceability': (0.8, 1.0)},
            'acoustic_vibes': {'acousticness': (0.6, 1.0)},
            'balanced': {'energy': (0.4, 0.7), 'valence': (0.4, 0.7)}
        }
        
        self.genre_complexity_scores = {
            'classical': 0.95, 'jazz': 0.90, 'progressive': 0.85,
            'rock': 0.75, 'indie': 0.70, 'pop': 0.60, 'hip-hop': 0.65
        }
    
    def analyze_audio_features(self, tracks, genres=None, albums=None, artist_name=None):
        """Robust AI analysis using only top track metadata, artist genres, and album info."""
        if not tracks:
            return {}

        # Calculate average popularity, duration, explicit ratio
        popularities = [t.get('popularity', 0) for t in tracks if t.get('popularity') is not None]
        durations = [t.get('duration_ms', 0) for t in tracks if t.get('duration_ms') is not None]
        explicit_count = sum(1 for t in tracks if t.get('explicit'))
        total_tracks = len(tracks)

        avg_popularity = sum(popularities) / len(popularities) if popularities else 0
        avg_duration = sum(durations) / len(durations) if durations else 0
        explicit_ratio = explicit_count / total_tracks if total_tracks else 0

        # Genre-based sophisticated analysis
        genres = genres or []
        genre_str = ', '.join(genres).lower()
        
        # Determine primary genre and characteristics
        genre_analysis = self._analyze_genre_characteristics(genre_str, avg_popularity, explicit_ratio, durations, artist_name)
        
        mood = genre_analysis['mood']
        complexity = genre_analysis['complexity']
        recommendations = genre_analysis['recommendations']

        # Popularity-based mainstream appeal
        mainstream_appeal = min(int(avg_popularity * 1.2), 100)

        # Album trend: newer albums more popular?
        album_years = []
        if albums:
            for album in albums:
                try:
                    year = int(str(album.get('release_date', '')).split('-')[0])
                    album_years.append(year)
                except Exception:
                    continue
        trend = 'Stable'
        if album_years:
            if max(album_years) - min(album_years) > 5:
                trend = 'Evolving'

        # Compose the AI analysis result
        return {
            'audio_features': {
                'avg_popularity': avg_popularity,
                'avg_duration_ms': avg_duration,
                'explicit_ratio': explicit_ratio
            },
            'mood_profile': {
                'primary_mood': mood,
                'confidence': 0.8
            },
            'complexity_score': complexity,
            'mainstream_appeal': mainstream_appeal,
            'trend': trend,
            'track_count': total_tracks,
            'analysis_timestamp': datetime.now().isoformat(),
            'recommendations': recommendations
        }
    
    def _analyze_genre_characteristics(self, genre_str, avg_popularity, explicit_ratio, durations, artist_name):
        """Generate artist-specific personalized mood profiles and recommendations"""
        avg_duration_min = (sum(durations) / len(durations) / 60000) if durations else 3.5
        artist_lower = artist_name.lower() if artist_name else ''
        
        # Artist-specific personalized analysis
        personalized_analysis = self._get_artist_persona(artist_lower, avg_popularity, explicit_ratio)
        if personalized_analysis:
            return personalized_analysis
        
        # Fallback to genre-based analysis if no specific persona found
        return self._get_genre_based_analysis(genre_str, avg_popularity, explicit_ratio, artist_name)

    def _get_artist_persona(self, artist_lower, avg_popularity, explicit_ratio):
        """Get personalized analysis for specific artists"""
        
        # Pop Icons & Legends
        if 'michael jackson' in artist_lower:
            return {
                'mood': 'Legendary & Timeless',
                'complexity': 95,
                'recommendations': [
                    "The undisputed King of Pop who redefined music, dance, and entertainment forever",
                    "Revolutionary artistry that transcended racial barriers and cultural boundaries worldwide",
                    "Every beat, every move, every note is pure musical history in motion"
                ]
            }
        elif 'taylor swift' in artist_lower:
            return {
                'mood': 'Storytelling Mastermind',
                'complexity': 85,
                'recommendations': [
                    "Swift's songwriting genius transforms personal experiences into universal anthems",
                    "From country roots to pop domination - a fearless evolution that redefined success",
                    "Each album era represents a new chapter in the most compelling musical autobiography ever written"
                ]
            }
        elif 'beyoncé' in artist_lower or 'beyonce' in artist_lower:
            return {
                'mood': 'Empowering Excellence',
                'complexity': 90,
                'recommendations': [
                    "Queen B's vocal powerhouse delivery combined with fierce independence and artistic vision",
                    "From Destiny's Child to solo reign - every performance is a masterclass in pure talent",
                    "Beyoncé doesn't just make music; she creates cultural movements and empowers generations"
                ]
            }
        
        # Hip-Hop Royalty
        elif 'drake' in artist_lower:
            return {
                'mood': 'Melodic Vulnerability',
                'complexity': 70,
                'recommendations': [
                    "The 6 God who popularized singing-rap and emotional transparency in hip-hop",
                    "Drake's ability to be both tough and tender revolutionized what rap could express",
                    "From Toronto to the world - every track feels like a personal conversation with greatness"
                ]
            }
        elif 'kendrick lamar' in artist_lower:
            return {
                'mood': 'Conscious Genius',
                'complexity': 95,
                'recommendations': [
                    "Kendrick's lyrical complexity and social consciousness define modern hip-hop excellence",
                    "Each album is a conceptual masterpiece that challenges listeners and society alike",
                    "The poet laureate of rap who proves hip-hop can be both street-smart and intellectually profound"
                ]
            }
        elif 'kanye west' in artist_lower or 'ye ' in artist_lower:
            return {
                'mood': 'Innovative Disruption',
                'complexity': 88,
                'recommendations': [
                    "Yeezy's production genius and boundary-pushing artistry changed hip-hop forever",
                    "Love him or hate him, Kanye's influence on music and culture is undeniable",
                    "Every album era represents a complete reinvention of sound and artistic vision"
                ]
            }
        elif 'yeat' in artist_lower:
            return {
                'mood': 'Hypnotic Innovation',
                'complexity': 60,
                'recommendations': [
                    "Yeat's bell-laden beats and unique vocal style created a whole new wave in rap",
                    "If you like the sound of success mixed with experimental trap, this is your artist",
                    "The underground king who brought a fresh, addictive sound to mainstream attention"
                ]
            }
        elif 'travis scott' in artist_lower:
            return {
                'mood': 'Psychedelic Energy',
                'complexity': 75,
                'recommendations': [
                    "La Flame's atmospheric production creates immersive sonic experiences like no other",
                    "Travis Scott concerts aren't just shows - they're transcendent musical journeys",
                    "Auto-tuned vocals meet orchestral grandeur in the most epic way possible"
                ]
            }
        
        # Rock Legends
        elif 'the beatles' in artist_lower:
            return {
                'mood': 'Revolutionary Harmony',
                'complexity': 100,
                'recommendations': [
                    "The Fab Four who invented modern pop music and changed the world forever",
                    "Every song is a piece of musical DNA that influenced every artist who came after",
                    "From 'Love Me Do' to 'Abbey Road' - the greatest musical journey in human history"
                ]
            }
        elif 'queen' in artist_lower and 'freddie' in artist_lower:
            return {
                'mood': 'Theatrical Majesty',
                'complexity': 90,
                'recommendations': [
                    "Freddie Mercury's operatic voice and Queen's genre-defying anthems are pure rock royalty",
                    "Every song is a stadium-filling epic designed to make you feel invincible",
                    "We Will Rock You, We Are The Champions - these aren't just songs, they're battle cries"
                ]
            }
        elif 'led zeppelin' in artist_lower:
            return {
                'mood': 'Mystical Power',
                'complexity': 85,
                'recommendations': [
                    "Zeppelin's heavy blues and mystical lyrics created the blueprint for hard rock",
                    "Jimmy Page's guitar wizardry meets Robert Plant's banshee wail in perfect harmony",
                    "Stairway to Heaven isn't just a song - it's a spiritual experience through sound"
                ]
            }
        
        # R&B Royalty
        elif 'whitney houston' in artist_lower:
            return {
                'mood': 'Vocal Perfection',
                'complexity': 95,
                'recommendations': [
                    "Whitney's voice was a force of nature that redefined what human vocals could achieve",
                    "The gold standard for vocal excellence - every note was delivered with divine precision",
                    "I Will Always Love You isn't just a cover - it's the definitive version that surpassed the original"
                ]
            }
        elif 'stevie wonder' in artist_lower:
            return {
                'mood': 'Soulful Innovation',
                'complexity': 90,
                'recommendations': [
                    "Stevie's musical genius spans soul, funk, pop, and R&B with unmatched creativity",
                    "A one-man orchestra who plays every instrument and writes timeless classics",
                    "Superstition, Sir Duke, Isn't She Lovely - each song is a masterpiece of joy and innovation"
                ]
            }
        
        # Modern Pop Phenomena
        elif 'billie eilish' in artist_lower:
            return {
                'mood': 'Dark Pop Innovation',
                'complexity': 70,
                'recommendations': [
                    "Billie's whispered vocals and dark aesthetics redefined what pop music could be",
                    "A Gen Z icon who proves you don't need to be loud to make the biggest impact",
                    "Bad Guy changed the game - minimalist production meets maximum artistic impact"
                ]
            }
        elif 'the weeknd' in artist_lower:
            return {
                'mood': 'Nocturnal Seduction',
                'complexity': 80,
                'recommendations': [
                    "Abel's dark R&B and cinematic production create the perfect soundtrack for midnight drives",
                    "From mysterious mixtapes to Super Bowl headliner - the ultimate artistic evolution",
                    "Blinding Lights and Can't Feel My Face prove he's master of both darkness and light"
                ]
            }
        elif 'dua lipa' in artist_lower:
            return {
                'mood': 'Disco Revival Queen',
                'complexity': 65,
                'recommendations': [
                    "Dua Lipa brought back disco-pop with modern sophistication and irresistible grooves",
                    "Future Nostalgia wasn't just an album - it was a time machine to the dance floor",
                    "Levitating, Don't Start Now - pure dancefloor euphoria with impeccable production"
                ]
            }
        
        # Electronic/EDM Artists
        elif 'daft punk' in artist_lower:
            return {
                'mood': 'Robotic Perfection',
                'complexity': 85,
                'recommendations': [
                    "The French robots who made electronic music cool and brought house to the masses",
                    "Get Lucky, One More Time - timeless electronic anthems that transcend genres",
                    "Their helmets hid their faces but revealed the future of music production"
                ]
            }
        elif 'skrillex' in artist_lower:
            return {
                'mood': 'Bass-Dropping Chaos',
                'complexity': 70,
                'recommendations': [
                    "Skrillex turned dubstep from underground noise into mainstream earthquake-inducing drops",
                    "Scary Monsters brought the bass and changed electronic music forever",
                    "When the beat drops, your soul ascends - this is organized musical chaos at its finest"
                ]
            }
        
        # Country Legends
        elif 'johnny cash' in artist_lower:
            return {
                'mood': 'Outlaw Authenticity',
                'complexity': 75,
                'recommendations': [
                    "The Man in Black whose deep voice and outlaw spirit defined authentic country music",
                    "Johnny Cash's covers of modern songs proved that great music transcends time and genre",
                    "Ring of Fire, Hurt - whether original or cover, Cash made every song his own"
                ]
            }
        
        # Alternative/Indie Icons
        elif 'radiohead' in artist_lower:
            return {
                'mood': 'Experimental Melancholy',
                'complexity': 95,
                'recommendations': [
                    "Radiohead's experimental genius challenges listeners while creating beautiful sonic landscapes",
                    "OK Computer predicted our digital dystopia with haunting accuracy and gorgeous melodies",
                    "Thom Yorke's falsetto paired with innovative production creates art that transcends music"
                ]
            }
        elif 'nirvana' in artist_lower:
            return {
                'mood': 'Grunge Authenticity',
                'complexity': 70,
                'recommendations': [
                    "Kurt Cobain's raw emotion and Nirvana's grunge revolution spoke for a generation",
                    "Smells Like Teen Spirit wasn't just a hit - it was a generational battle cry",
                    "The band that proved three chords and the truth could change the world"
                ]
            }
        
        return None  # No specific persona found
    
    def _get_genre_based_analysis(self, genre_str, avg_popularity, explicit_ratio, artist_name):
        """Fallback genre-based analysis for artists without specific personas"""
        
        # R&B/Soul Analysis
        if any(g in genre_str for g in ['r&b', 'rnb', 'soul', 'neo-soul']):
            return {
                'mood': 'Smooth & Soulful',
                'complexity': 70,
                'recommendations': [
                    f"{artist_name} crafts emotionally rich R&B with sophisticated vocal arrangements",
                    f"Expect smooth grooves and intimate storytelling that defines modern soul music",
                    f"Perfect for late-night listening with emphasis on vocal prowess and melodic depth"
                ]
            }
        
        # Hip-Hop/Rap Analysis
        elif any(g in genre_str for g in ['hip-hop', 'rap', 'trap', 'drill']):
            if explicit_ratio > 0.7:
                mood_desc = "Raw & Unfiltered"
                recs = [
                    f"{artist_name} delivers hard-hitting rap with uncompromising lyrical content",
                    f"Authentic street narratives with aggressive production and powerful delivery",
                    f"Not for the faint-hearted - expect intense themes and bold artistic expression"
                ]
            else:
                mood_desc = "Lyrical & Conscious"
                recs = [
                    f"{artist_name} represents conscious rap with thoughtful wordplay and social commentary",
                    f"Intelligent hip-hop that balances mainstream appeal with lyrical substance",
                    f"Family-friendly rap that proves you can be profound without profanity"
                ]
            return {
                'mood': mood_desc,
                'complexity': 65,
                'recommendations': recs
            }
        
        # Rock Analysis
        elif any(g in genre_str for g in ['rock', 'metal', 'punk', 'grunge']):
            if 'metal' in genre_str or 'punk' in genre_str:
                return {
                    'mood': 'Intense & Aggressive',
                    'complexity': 75,
                    'recommendations': [
                        f"{artist_name} unleashes raw power through crushing riffs and aggressive vocals",
                        f"High-energy music that channels rebellion and emotional intensity",
                        f"Not background music - demands your full attention and respect"
                    ]
                }
            else:
                return {
                    'mood': 'Energetic & Anthemic',
                    'complexity': 60,
                    'recommendations': [
                        f"{artist_name} delivers classic rock energy with memorable hooks and guitar-driven sound",
                        f"Stadium-worthy anthems that blend technical skill with mass appeal",
                        f"Perfect for road trips and moments when you need to feel invincible"
                    ]
                }
        
        # Pop Analysis
        elif any(g in genre_str for g in ['pop', 'dance-pop', 'electropop']):
            if avg_popularity > 80:
                return {
                    'mood': 'Infectious & Chart-Topping',
                    'complexity': 35,
                    'recommendations': [
                        f"{artist_name} masters the art of irresistible pop hooks and mainstream appeal",
                        f"Expertly crafted singles designed to dominate charts and playlists worldwide",
                        f"The soundtrack to your best memories - instantly recognizable and eternally catchy"
                    ]
                }
            else:
                return {
                    'mood': 'Quirky & Alternative',
                    'complexity': 50,
                    'recommendations': [
                        f"{artist_name} offers refreshing pop sensibilities with unique artistic vision",
                        f"Accessible yet distinctive - pop music for listeners who crave something different",
                        f"Hidden gems that deserve more recognition in the mainstream landscape"
                    ]
                }
        
        # Electronic/EDM Analysis
        elif any(g in genre_str for g in ['electronic', 'edm', 'techno', 'house', 'dubstep']):
            return {
                'mood': 'Euphoric & Atmospheric',
                'complexity': 55,
                'recommendations': [
                    f"{artist_name} creates immersive electronic soundscapes perfect for both clubs and headphones",
                    f"Cutting-edge production with beats that make your pulse sync to the rhythm",
                    f"Digital artistry that transforms simple sounds into transcendent musical experiences"
                ]
            }
        
        # Jazz Analysis
        elif any(g in genre_str for g in ['jazz', 'blues', 'swing']):
            return {
                'mood': 'Sophisticated & Timeless',
                'complexity': 85,
                'recommendations': [
                    f"{artist_name} upholds jazz tradition while pushing musical boundaries with technical excellence",
                    f"Complex harmonies and improvisation showcase decades of musical evolution",
                    f"For connoisseurs who appreciate the intersection of technical skill and emotional expression"
                ]
            }
        
        # Country Analysis
        elif any(g in genre_str for g in ['country', 'folk', 'americana']):
            return {
                'mood': 'Authentic & Storytelling',
                'complexity': 45,
                'recommendations': [
                    f"{artist_name} weaves compelling narratives through authentic country musicianship",
                    f"Honest songwriting that captures the essence of human experience and rural life",
                    f"Traditional values meet modern production in music that speaks to the heart"
                ]
            }
        
        # Indie Analysis
        elif any(g in genre_str for g in ['indie', 'alternative', 'art']):
            return {
                'mood': 'Creative & Unconventional',
                'complexity': 65,
                'recommendations': [
                    f"{artist_name} challenges musical conventions with innovative indie artistry",
                    f"Experimental approach that prioritizes artistic integrity over commercial success",
                    f"For listeners who value creativity and authenticity above mainstream trends"
                ]
            }
        
        # Classical/Ambient Analysis
        elif any(g in genre_str for g in ['classical', 'ambient', 'new age', 'instrumental']):
            return {
                'mood': 'Meditative & Cinematic',
                'complexity': 80,
                'recommendations': [
                    f"{artist_name} creates expansive soundscapes that transport listeners to otherworldly realms",
                    f"Atmospheric compositions perfect for meditation, focus, and emotional reflection",
                    f"Instrumental mastery that speaks without words and heals without medicine"
                ]
            }
        
        # Default/Mixed Genre Analysis
        else:
            return {
                'mood': 'Eclectic & Versatile',
                'complexity': 55,
                'recommendations': [
                    f"{artist_name} defies easy categorization with a diverse and dynamic musical approach",
                    f"Genre-blending artistry that keeps listeners guessing and always engaged",
                    f"Musical chameleon who adapts styles while maintaining a distinctive artistic voice"
                ]
            }
    
    def _get_genre_based_analysis(self, genre_str, avg_popularity, explicit_ratio, artist_name):
        
        # R&B/Soul Analysis
        if any(g in genre_str for g in ['r&b', 'rnb', 'soul', 'neo-soul']):
            return {
                'mood': 'Smooth & Soulful',
                'complexity': 70,
                'recommendations': [
                    f"{artist_name} crafts emotionally rich R&B with sophisticated vocal arrangements",
                    f"Expect smooth grooves and intimate storytelling that defines modern soul music",
                    f"Perfect for late-night listening with emphasis on vocal prowess and melodic depth"
                ]
            }
        
        # Hip-Hop/Rap Analysis
        elif any(g in genre_str for g in ['hip-hop', 'rap', 'trap', 'drill']):
            if explicit_ratio > 0.7:
                mood_desc = "Raw & Unfiltered"
                recs = [
                    f"{artist_name} delivers hard-hitting rap with uncompromising lyrical content",
                    f"Authentic street narratives with aggressive production and powerful delivery",
                    f"Not for the faint-hearted - expect intense themes and bold artistic expression"
                ]
            else:
                mood_desc = "Lyrical & Conscious"
                recs = [
                    f"{artist_name} represents conscious rap with thoughtful wordplay and social commentary",
                    f"Intelligent hip-hop that balances mainstream appeal with lyrical substance",
                    f"Family-friendly rap that proves you can be profound without profanity"
                ]
            return {
                'mood': mood_desc,
                'complexity': 65,
                'recommendations': recs
            }
        
        # Rock Analysis
        elif any(g in genre_str for g in ['rock', 'metal', 'punk', 'grunge']):
            if 'metal' in genre_str or 'punk' in genre_str:
                return {
                    'mood': 'Intense & Aggressive',
                    'complexity': 75,
                    'recommendations': [
                        f"{artist_name} unleashes raw power through crushing riffs and aggressive vocals",
                        f"High-energy music that channels rebellion and emotional intensity",
                        f"Not background music - demands your full attention and respect"
                    ]
                }
            else:
                return {
                    'mood': 'Energetic & Anthemic',
                    'complexity': 60,
                    'recommendations': [
                        f"{artist_name} delivers classic rock energy with memorable hooks and guitar-driven sound",
                        f"Stadium-worthy anthems that blend technical skill with mass appeal",
                        f"Perfect for road trips and moments when you need to feel invincible"
                    ]
                }
        
        # Pop Analysis
        elif any(g in genre_str for g in ['pop', 'dance-pop', 'electropop']):
            if avg_popularity > 80:
                return {
                    'mood': 'Infectious & Chart-Topping',
                    'complexity': 35,
                    'recommendations': [
                        f"{artist_name} masters the art of irresistible pop hooks and mainstream appeal",
                        f"Expertly crafted singles designed to dominate charts and playlists worldwide",
                        f"The soundtrack to your best memories - instantly recognizable and eternally catchy"
                    ]
                }
            else:
                return {
                    'mood': 'Quirky & Alternative',
                    'complexity': 50,
                    'recommendations': [
                        f"{artist_name} offers refreshing pop sensibilities with unique artistic vision",
                        f"Accessible yet distinctive - pop music for listeners who crave something different",
                        f"Hidden gems that deserve more recognition in the mainstream landscape"
                    ]
                }
        
        # Electronic/EDM Analysis
        elif any(g in genre_str for g in ['electronic', 'edm', 'techno', 'house', 'dubstep']):
            return {
                'mood': 'Euphoric & Atmospheric',
                'complexity': 55,
                'recommendations': [
                    f"{artist_name} creates immersive electronic soundscapes perfect for both clubs and headphones",
                    f"Cutting-edge production with beats that make your pulse sync to the rhythm",
                    f"Digital artistry that transforms simple sounds into transcendent musical experiences"
                ]
            }
        
        # Jazz Analysis
        elif any(g in genre_str for g in ['jazz', 'blues', 'swing']):
            return {
                'mood': 'Sophisticated & Timeless',
                'complexity': 85,
                'recommendations': [
                    f"{artist_name} upholds jazz tradition while pushing musical boundaries with technical excellence",
                    f"Complex harmonies and improvisation showcase decades of musical evolution",
                    f"For connoisseurs who appreciate the intersection of technical skill and emotional expression"
                ]
            }
        
        # Country Analysis
        elif any(g in genre_str for g in ['country', 'folk', 'americana']):
            return {
                'mood': 'Authentic & Storytelling',
                'complexity': 45,
                'recommendations': [
                    f"{artist_name} weaves compelling narratives through authentic country musicianship",
                    f"Honest songwriting that captures the essence of human experience and rural life",
                    f"Traditional values meet modern production in music that speaks to the heart"
                ]
            }
        
        # Indie Analysis
        elif any(g in genre_str for g in ['indie', 'alternative', 'art']):
            return {
                'mood': 'Creative & Unconventional',
                'complexity': 65,
                'recommendations': [
                    f"{artist_name} challenges musical conventions with innovative indie artistry",
                    f"Experimental approach that prioritizes artistic integrity over commercial success",
                    f"For listeners who value creativity and authenticity above mainstream trends"
                ]
            }
        
        # Classical/Ambient Analysis
        elif any(g in genre_str for g in ['classical', 'ambient', 'new age', 'instrumental']):
            return {
                'mood': 'Meditative & Cinematic',
                'complexity': 80,
                'recommendations': [
                    f"{artist_name} creates expansive soundscapes that transport listeners to otherworldly realms",
                    f"Atmospheric compositions perfect for meditation, focus, and emotional reflection",
                    f"Instrumental mastery that speaks without words and heals without medicine"
                ]
            }
        
        # Default/Mixed Genre Analysis
        else:
            return {
                'mood': 'Eclectic & Versatile',
                'complexity': 55,
                'recommendations': [
                    f"{artist_name} defies easy categorization with a diverse and dynamic musical approach",
                    f"Genre-blending artistry that keeps listeners guessing and always engaged",
                    f"Musical chameleon who adapts styles while maintaining a distinctive artistic voice"
                ]
            }

    def _generate_smart_recommendations(self, artist_name, genres, avg_popularity, explicit_ratio, avg_duration, album_years, total_tracks):
        """Generate truly unique recommendations based on artist's specific characteristics"""
        recommendations = []
        genre_str = ', '.join(genres).lower() if genres else ''
        
        # Artist name analysis for context
        name_lower = artist_name.lower() if artist_name else ''
        
        # Unique genre + popularity combinations
        if 'pop' in genre_str:
            if avg_popularity > 80:
                recommendations.append(f"{artist_name} dominates mainstream charts - perfect for discovering what's defining pop culture right now")
            elif avg_popularity < 40:
                recommendations.append(f"Underground pop gem - {artist_name} offers refreshing alternatives to mainstream radio")
            else:
                recommendations.append(f"{artist_name} balances commercial appeal with artistic integrity - ideal for sophisticated pop lovers")
        
        elif any(g in genre_str for g in ['rock', 'metal', 'punk']):
            if explicit_ratio > 0.6:
                recommendations.append(f"Raw, unfiltered energy - {artist_name} delivers authentic rock expression without compromise")
            elif avg_duration > 300000:  # 5+ minutes
                recommendations.append(f"Epic compositions - {artist_name} crafts extended musical journeys for serious rock enthusiasts")
            else:
                recommendations.append(f"{artist_name} channels classic rock spirit into modern accessibility")
        
        elif any(g in genre_str for g in ['hip-hop', 'rap', 'trap']):
            if explicit_ratio > 0.7:
                recommendations.append(f"Authentic street narratives - {artist_name} represents uncompromising hip-hop storytelling")
            elif avg_popularity > 75:
                recommendations.append(f"Cultural trendsetter - {artist_name} shapes the sound of contemporary hip-hop")
            else:
                recommendations.append(f"{artist_name} delivers lyrical depth beyond mainstream hip-hop trends")
        
        elif any(g in genre_str for g in ['country', 'folk', 'americana']):
            if album_years and len(album_years) > 5:
                recommendations.append(f"Generational storyteller - {artist_name} chronicles American life across decades")
            else:
                recommendations.append(f"{artist_name} preserves authentic country traditions while speaking to modern experiences")
        
        elif any(g in genre_str for g in ['electronic', 'techno', 'house', 'edm']):
            if avg_duration > 360000:  # 6+ minutes
                recommendations.append(f"Immersive sonic architect - {artist_name} builds extended electronic landscapes for deep listening")
            else:
                recommendations.append(f"{artist_name} masters electronic precision perfect for both clubs and personal listening")
        
        elif any(g in genre_str for g in ['jazz', 'blues', 'soul']):
            recommendations.append(f"Musical sophistication - {artist_name} represents timeless artistry for discerning listeners")
        
        elif any(g in genre_str for g in ['indie', 'alternative']):
            if avg_popularity < 50:
                recommendations.append(f"Indie discovery - {artist_name} offers authentic artistry away from commercial pressures")
            else:
                recommendations.append(f"{artist_name} bridges underground creativity with broader appeal")
        
        # Career stage analysis
        if album_years:
            career_span = max(album_years) - min(album_years)
            if career_span > 15:
                recommendations.append(f"Legendary consistency - {artist_name} represents decades of musical evolution and mastery")
            elif career_span < 3:
                recommendations.append(f"Rising force - {artist_name} showcases the future direction of {genre_str.split(',')[0] if genre_str else 'music'}")
        
        # Track quantity insights
        if total_tracks > 15:
            recommendations.append(f"Prolific creativity - {artist_name} offers extensive catalogs for deep exploration")
        elif total_tracks < 8:
            recommendations.append(f"Quality over quantity - {artist_name} curates every release for maximum impact")
        
        # Explicit content context
        if explicit_ratio > 0.8:
            recommendations.append(f"Unfiltered expression - {artist_name} delivers raw, authentic artistic vision")
        elif explicit_ratio == 0:
            recommendations.append(f"Universal accessibility - {artist_name} creates music for all audiences without compromising artistry")
        
        # Fallback for edge cases
        if not recommendations:
            recommendations.append(f"{artist_name} offers unique musical perspectives worth exploring")
        
        # Return max 3 most relevant recommendations
        return recommendations[:3]
    
    def _calculate_audio_statistics(self, features_list):
        """Calculate detailed audio feature statistics"""
        feature_keys = ['danceability', 'energy', 'valence', 'acousticness', 
                       'instrumentalness', 'liveness', 'speechiness', 'tempo']
        
        stats = {}
        for key in feature_keys:
            values = [f[key] for f in features_list if f.get(key) is not None]
            if values:
                stats[key] = {
                    'mean': sum(values) / len(values),
                    'min': min(values),
                    'max': max(values),
                    'std': self._calculate_std(values)
                }
        
        return stats
    
    def _calculate_std(self, values):
        """Calculate standard deviation"""
        if len(values) < 2:
            return 0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5
    
    def _generate_advanced_mood_profile(self, audio_stats):
        """Generate sophisticated mood profile"""
        if not audio_stats:
            return {'primary_mood': 'unknown', 'confidence': 0.0}
        
        energy = audio_stats.get('energy', {}).get('mean', 0.5)
        valence = audio_stats.get('valence', {}).get('mean', 0.5)
        danceability = audio_stats.get('danceability', {}).get('mean', 0.5)
        acousticness = audio_stats.get('acousticness', {}).get('mean', 0.5)
        
        # Advanced mood classification
        if energy > 0.75 and valence > 0.7:
            return {'primary_mood': '🔥 High-Energy Euphoric', 'confidence': 0.9}
        elif energy > 0.7 and valence < 0.3:
            return {'primary_mood': '⚡ Intense & Aggressive', 'confidence': 0.85}
        elif energy < 0.3 and valence > 0.7:
            return {'primary_mood': '😌 Peaceful & Uplifting', 'confidence': 0.8}
        elif energy < 0.3 and valence < 0.3:
            return {'primary_mood': '😔 Melancholic & Contemplative', 'confidence': 0.85}
        elif danceability > 0.8:
            return {'primary_mood': '💃 Dancefloor Ready', 'confidence': 0.9}
        elif acousticness > 0.7:
            return {'primary_mood': '🎸 Acoustic & Intimate', 'confidence': 0.8}
        else:
            return {'primary_mood': '🎵 Balanced & Versatile', 'confidence': 0.6}
    
    def _calculate_musical_complexity(self, audio_stats):
        """Calculate musical complexity score (0-100)"""
        if not audio_stats:
            return 50
        
        complexity_factors = {
            'instrumentalness': audio_stats.get('instrumentalness', {}).get('mean', 0) * 20,
            'tempo_variance': min(audio_stats.get('tempo', {}).get('std', 0) / 50, 1) * 15,
            'acoustic_balance': abs(0.5 - audio_stats.get('acousticness', {}).get('mean', 0.5)) * 10,
            'energy_dynamics': audio_stats.get('energy', {}).get('std', 0) * 25
        }
        
        base_score = 40
        complexity_score = base_score + sum(complexity_factors.values())
        return min(max(complexity_score, 0), 100)
    
    def generate_discovery_insights(self, artist_name, genres, audio_analysis):
        """Generate advanced discovery insights"""
        insights = {
            'discoverability_score': self._calculate_discoverability(audio_analysis, genres),
            'genre_diversity': len(set(genres)) if genres else 0,
            'mainstream_appeal': self._calculate_mainstream_appeal(audio_analysis),
            'uniqueness_factor': self._calculate_uniqueness(audio_analysis, genres),
            'recommendations': self._generate_recommendations(audio_analysis, genres)
        }
        
        return insights
    
    def _calculate_discoverability(self, audio_analysis, genres):
        """Calculate how discoverable this artist is (0-100)"""
        if not audio_analysis:
            return random.randint(60, 90)
        
        base_score = 50
        popularity = audio_analysis.get('audio_features', {}).get('avg_popularity', 50)
        
        # Popular artists are more discoverable
        discovery_score = min(int(popularity * 1.3), 95)
        
        # Add some randomness for variety
        discovery_score += random.randint(-10, 15)
        
        return max(min(discovery_score, 100), 30)  # Keep between 30-100
        
        if 0.3 <= energy_mean <= 0.8:
            base_score += 15
        if 0.4 <= valence_mean <= 0.9:
            base_score += 15
        
        # Popular genres boost discoverability
        popular_genres = ['pop', 'rock', 'hip-hop', 'indie', 'electronic']
        if genres:
            for genre in genres:
                if any(pop in genre.lower() for pop in popular_genres):
                    base_score += 10
                    break
        
        return min(base_score, 100)
    
    def _calculate_mainstream_appeal(self, audio_analysis):
        """Calculate mainstream appeal (0-100)"""
        if not audio_analysis:
            return 50
        
        features = audio_analysis.get('audio_features', {})
        
        # Mainstream characteristics
        danceability = features.get('danceability', {}).get('mean', 0.5)
        energy = features.get('energy', {}).get('mean', 0.5)
        valence = features.get('valence', {}).get('mean', 0.5)
        
        appeal_score = (danceability * 30 + energy * 25 + valence * 25 + 20)
        return min(max(appeal_score * 100, 0), 100)
    
    def _calculate_uniqueness(self, audio_analysis, genres):
        """Calculate uniqueness factor (0-100)"""
        uniqueness = 50
        
        if audio_analysis:
            features = audio_analysis.get('audio_features', {})
            
            # High instrumentalness is unique
            instrumentalness = features.get('instrumentalness', {}).get('mean', 0)
            uniqueness += instrumentalness * 25
            
            # Uncommon genres are unique
            unique_genres = ['experimental', 'avant-garde', 'noise', 'drone']
            if genres:
                for genre in genres:
                    if any(unique in genre.lower() for unique in unique_genres):
                        uniqueness += 20
                        break
        
        return min(max(uniqueness, 0), 100)
    
    def _generate_recommendations(self, audio_analysis, genres):
        """Generate smart recommendations based on analysis"""
        recommendations = []
        
        if not audio_analysis:
            return ['Explore more music to get personalized recommendations!']
        
        features = audio_analysis.get('audio_features', {})
        energy = features.get('energy', {}).get('mean', 0.5)
        valence = features.get('valence', {}).get('mean', 0.5)
        danceability = features.get('danceability', {}).get('mean', 0.5)
        
        if energy > 0.7 and danceability > 0.7:
            recommendations.append("Perfect for workout playlists and dance parties!")
        
        if valence > 0.8:
            recommendations.append("Great mood-boosting music for positive vibes!")
        
        if energy < 0.3 and valence < 0.5:
            recommendations.append("Ideal for introspective moments and late-night listening.")
        
        if features.get('acousticness', {}).get('mean', 0) > 0.6:
            recommendations.append("Perfect acoustic sound for intimate settings.")
        
        if not recommendations:
            recommendations.append("Versatile music suitable for various listening contexts.")
        
        return recommendations

# Initialize the intelligence engine
music_ai = MusicIntelligenceEngine()

def get_artist_title(artist_name, genres):
    """Get personalized title/nickname for the artist"""
    artist_lower = artist_name.lower() if artist_name else ''
    
    # Famous artist titles
    artist_titles = {
        'michael jackson': 'The King of Pop',
        'elvis presley': 'The King of Rock and Roll',
        'taylor swift': 'The Songwriting Mastermind',
        'beyoncé': 'Queen B',
        'beyonce': 'Queen B',
        'drake': 'The 6 God',
        'kendrick lamar': 'The Rap Genius',
        'kanye west': 'Yeezy',
        'ye': 'Yeezy',
        'yeat': 'The Bell King',
        'travis scott': 'La Flame',
        'the beatles': 'The Fab Four',
        'queen': 'Rock Royalty',
        'led zeppelin': 'The Masters of Hard Rock',
        'whitney houston': 'The Voice',
        'stevie wonder': 'The Genius',
        'billie eilish': 'The Dark Pop Princess',
        'the weeknd': 'The Nocturnal King',
        'dua lipa': 'The Disco Revival Queen',
        'daft punk': 'The Robot Legends',
        'skrillex': 'The Bass Drop King',
        'johnny cash': 'The Man in Black',
        'radiohead': 'The Experimental Masters',
        'nirvana': 'The Grunge Pioneers',
        'adele': 'The Soul Powerhouse',
        'bruno mars': 'The Showman',
        'ed sheeran': 'The Loop Pedal Virtuoso',
        'eminem': 'Slim Shady',
        'jay-z': 'HOV',
        'tupac': 'The Prophet',
        'biggie': 'The Notorious B.I.G.',
        'prince': 'The Purple One',
        'madonna': 'The Queen of Pop',
        'bob dylan': 'The Voice of a Generation',
        'aretha franklin': 'The Queen of Soul',
        'marvin gaye': 'The Prince of Soul',
        'frank sinatra': 'Ol\' Blue Eyes',
        'david bowie': 'The Starman',
        'jimi hendrix': 'The Guitar God',
        'bob marley': 'The Reggae Legend',
        'john lennon': 'The Dreamer',
        'freddie mercury': 'The Showman Supreme'
    }
    
    # Check for exact matches first
    for artist_key, title in artist_titles.items():
        if artist_key in artist_lower:
            return title
    
    # Generate title based on genres if no specific title found
    if genres:
        primary_genre = genres[0].lower()
        if 'pop' in primary_genre:
            return 'Pop Sensation'
        elif 'rap' in primary_genre or 'hip-hop' in primary_genre:
            return 'Hip-Hop Artist'
        elif 'rock' in primary_genre:
            return 'Rock Legend'
        elif 'r&b' in primary_genre or 'soul' in primary_genre:
            return 'R&B Star'
        elif 'country' in primary_genre:
            return 'Country Artist'
        elif 'electronic' in primary_genre or 'edm' in primary_genre:
            return 'Electronic Producer'
        elif 'jazz' in primary_genre:
            return 'Jazz Virtuoso'
        elif 'indie' in primary_genre or 'alternative' in primary_genre:
            return 'Indie Artist'
    
    return 'Musical Artist'  # Default fallback

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/search', methods=['POST'])
@rate_limit(max_requests=30, window=3600)
def search_albums():
    try:
        if not sp:
            return jsonify({'error': 'Spotify service unavailable'}), 503
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request data'}), 400
        
        query = data.get('query', '').strip()
        if not query:
            return jsonify({'error': 'Search query is required'}), 400
        
        if len(query) > 100:
            return jsonify({'error': 'Search query too long'}), 400
        
        # Track search analytics
        search_analytics[query.lower()] += 1
        
        # Search for artist and albums
        search_results = sp.search(q=query, type='artist,album', limit=20)
        
        if not search_results['artists']['items']:
            return jsonify({'error': 'No artists found'}), 404
        
        artist = search_results['artists']['items'][0]
        artist_id = artist['id']
        artist_name = artist['name']
        
        # Get artist's albums
        albums_result = sp.artist_albums(
            artist_id,
            album_type='album',
            limit=50
        )

        # Process albums (for display only)
        albums = []
        for album in albums_result['items']:
            if album['total_tracks'] > 0:
                albums.append({
                    'id': album['id'],
                    'name': album['name'],
                    'artist': album['artists'][0]['name'],
                    'image': album['images'][0]['url'] if album['images'] else None,
                    'release_date': album['release_date'],
                    'total_tracks': album['total_tracks'],
                    'spotify_url': album['external_urls']['spotify'],
                    'album_type': album.get('album_type', 'album')
                })

        # Use only the artist's top 20 tracks for AI analysis
        top_tracks = sp.artist_top_tracks(artist_id, country='US')
        top_track_ids = [track['id'] for track in top_tracks['tracks'][:20] if track.get('id')]
        all_audio_features = []
        failed_tracks = []
        if top_track_ids:
            for track_id in top_track_ids:
                try:
                    features = sp.audio_features([track_id])
                    if features and features[0] is not None:
                        all_audio_features.append(features[0])
                except spotipy.exceptions.SpotifyException as e:
                    logger.warning(f"Skipping track {track_id} due to Spotify API error: {e}")
                    failed_tracks.append(track_id)

        # If no audio features could be fetched, fall back to using available top track data
        if not all_audio_features:
            logger.warning("No audio features available from Spotify API; using top track metadata for analysis.")
            # Use only basic info from top_tracks for a minimal analysis
            all_audio_features = [
                {
                    'id': t['id'],
                    'popularity': t.get('popularity'),
                    'duration_ms': t.get('duration_ms'),
                    'explicit': t.get('explicit'),
                    'name': t.get('name'),
                }
                for t in top_tracks['tracks'][:20] if t.get('id')
            ]

        # Generate AI insights using robust metadata-based analysis
        artist_genres = artist.get('genres', [])
        music_analysis = music_ai.analyze_audio_features(all_audio_features, genres=artist_genres, albums=albums, artist_name=artist_name)
        discovery_insights = music_ai.generate_discovery_insights(
            artist_name, artist_genres, music_analysis
        )
        
        # Cache insights
        cache_key = hashlib.md5(f"{artist_id}_{datetime.now().date()}".encode()).hexdigest()
        music_insights_cache[cache_key] = {
            'analysis': music_analysis,
            'insights': discovery_insights,
            'timestamp': datetime.now().isoformat()
        }
        
        response_data = {
            'success': True,
            'artist': {
                'id': artist_id,
                'name': artist_name,
                'title': get_artist_title(artist_name, artist_genres),
                'genres': artist_genres,
                'primary_genre': artist_genres[0] if artist_genres else 'Unknown',
                'followers': artist.get('followers', {}).get('total', 0),
                'popularity': artist.get('popularity', 0),
                'image': artist['images'][0]['url'] if artist['images'] else None
            },
            'albums': albums,
            'music_analysis': music_analysis,
            'discovery_insights': discovery_insights,
            'total_results': len(albums),
            'search_timestamp': datetime.now().isoformat()
        }
        
        logger.info(f"Successful search for artist: {artist_name}")
        return jsonify(response_data)
        
    except spotipy.exceptions.SpotifyException as e:
        logger.error(f"Spotify API error: {e}")
        return jsonify({'error': 'Music service error. Please try again.'}), 502
        
    except Exception as e:
        import traceback
        logger.error(f"Unexpected error in search: {e}\n" + traceback.format_exc())
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/analytics')
@rate_limit(max_requests=10, window=3600)
def get_analytics():
    """Get search analytics and insights"""
    try:
        top_searches = dict(sorted(
            search_analytics.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10])
        
        total_searches = sum(search_analytics.values())
        
        analytics_data = {
            'total_searches': total_searches,
            'top_searches': top_searches,
            'unique_queries': len(search_analytics),
            'cache_size': len(music_insights_cache),
            'timestamp': datetime.now().isoformat()
        }
        
        return jsonify(analytics_data)
        
    except Exception as e:
        logger.error(f"Error getting analytics: {e}")
        return jsonify({'error': 'Analytics unavailable'}), 500

@app.route('/api/heart-artist', methods=['POST'])
def heart_artist():
    """Heart/like an artist"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request data'}), 400
        
        artist_id = data.get('artist_id')
        artist_name = data.get('artist_name')
        genres = data.get('genres', [])
        image = data.get('image')
        
        if not artist_id or not artist_name:
            return jsonify({'error': 'Artist ID and name required'}), 400
        
        # Check if already liked
        existing = next((a for a in user_preferences['liked_artists_data'] 
                        if a['artist_id'] == artist_id), None)
        
        if existing:
            return jsonify({
                'success': False,
                'error': 'Artist already liked',
                'message': 'This artist is already in your favorites'
            }), 409
        
        # Add to liked artists data with complete information
        artist_data = {
            'artist_id': artist_id,
            'artist_name': artist_name,
            'genres': genres,
            'image': image,
            'liked_at': datetime.now().isoformat()
        }
        
        user_preferences['liked_artists_data'].append(artist_data)
        user_preferences['liked_artists'].add(artist_id)  # Keep for backward compatibility
        
        # Update genre preferences
        for genre in genres:
            user_preferences['genre_preferences'][genre.lower()] += 1
        
        # Add to listening history
        user_preferences['listening_history'].append({
            'artist_id': artist_id,
            'artist_name': artist_name,
            'genres': genres,
            'timestamp': datetime.now().isoformat(),
            'action': 'liked'
        })
        
        return jsonify({
            'success': True,
            'message': f'{artist_name} added to favorites',
            'total_likes': len(user_preferences['liked_artists'])
        })
        
    except Exception as e:
        logger.error(f"Heart artist error: {e}")
        return jsonify({'error': 'Failed to save artist'}), 500

@app.route('/api/save-album', methods=['POST'])
def save_album():
    """Save an album for later"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request data'}), 400
        
        album_data = {
            'album_id': data.get('album_id'),
            'album_name': data.get('album_name'),
            'artist_name': data.get('artist_name'),
            'artist_id': data.get('artist_id'),
            'release_date': data.get('release_date'),
            'image': data.get('image'),
            'total_tracks': data.get('total_tracks', 0),
            'saved_at': datetime.now().isoformat()
        }
        
        if not album_data['album_id'] or not album_data['album_name']:
            return jsonify({'error': 'Album ID and name required'}), 400
        
        # Check if already saved
        existing = next((a for a in user_preferences['saved_albums'] 
                        if a['album_id'] == album_data['album_id']), None)
        
        if existing:
            return jsonify({
                'success': False,
                'error': 'Album already saved',
                'message': 'This album is already in your collection'
            }), 409  # Conflict status code
        
        user_preferences['saved_albums'].append(album_data)
        
        return jsonify({
            'success': True,
            'message': f'Album "{album_data["album_name"]}" saved to your collection',
            'total_saved': len(user_preferences['saved_albums'])
        })
        
    except Exception as e:
        logger.error(f"Save album error: {e}")
        return jsonify({'error': 'Failed to save album'}), 500

@app.route('/api/unsave-album', methods=['POST'])
def unsave_album():
    """Remove an album from saved collection"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request data'}), 400
        
        album_id = data.get('album_id')
        if not album_id:
            return jsonify({'error': 'Album ID required'}), 400
        
        # Find and remove the album
        original_count = len(user_preferences['saved_albums'])
        user_preferences['saved_albums'] = [
            album for album in user_preferences['saved_albums'] 
            if album['album_id'] != album_id
        ]
        
        if len(user_preferences['saved_albums']) == original_count:
            return jsonify({
                'success': False,
                'error': 'Album not found in saved collection'
            }), 404
        
        return jsonify({
            'success': True,
            'message': 'Album removed from your collection',
            'total_saved': len(user_preferences['saved_albums'])
        })
        
    except Exception as e:
        logger.error(f"Unsave album error: {e}")
        return jsonify({'error': 'Failed to unsave album'}), 500

@app.route('/api/unlike-artist', methods=['POST'])
def unlike_artist():
    """Remove an artist from liked collection"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request data'}), 400
        
        artist_id = data.get('artist_id')
        artist_name = data.get('artist_name', 'Unknown Artist')
        
        if not artist_id:
            return jsonify({'error': 'Artist ID required'}), 400
        
        # Remove from liked artists data
        original_count = len(user_preferences['liked_artists_data'])
        user_preferences['liked_artists_data'] = [
            artist for artist in user_preferences['liked_artists_data'] 
            if artist['artist_id'] != artist_id
        ]
        
        # Remove from liked artists set
        if artist_id in user_preferences['liked_artists']:
            user_preferences['liked_artists'].remove(artist_id)
        
        if len(user_preferences['liked_artists_data']) == original_count:
            return jsonify({
                'success': False,
                'error': 'Artist not found in liked collection'
            }), 404
            
        # Add to listening history
        user_preferences['listening_history'].append({
            'artist_id': artist_id,
            'artist_name': artist_name,
            'timestamp': datetime.now().isoformat(),
            'action': 'unliked'
        })
        
        return jsonify({
            'success': True,
            'message': f'{artist_name} removed from favorites',
            'total_likes': len(user_preferences['liked_artists'])
        })
        
    except Exception as e:
        logger.error(f"Unlike artist error: {e}")
        return jsonify({'error': 'Failed to unlike artist'}), 500

@app.route('/api/clear-collection', methods=['POST'])
def clear_collection():
    """Clear all user collection data"""
    try:
        # Reset all user preferences
        user_preferences['liked_artists'].clear()
        user_preferences['liked_artists_data'].clear()
        user_preferences['saved_albums'].clear()
        user_preferences['genre_preferences'].clear()
        user_preferences['listening_history'].clear()
        
        return jsonify({
            'success': True,
            'message': 'Collection cleared successfully'
        })
        
    except Exception as e:
        logger.error(f"Clear collection error: {e}")
        return jsonify({'error': 'Failed to clear collection'}), 500

@app.route('/api/user-preferences')
def get_user_preferences():
    """Get user's preferences and collection"""
    try:
        return jsonify({
            'success': True,
            'data': {
                'liked_count': len(user_preferences['liked_artists']),
                'saved_albums_count': len(user_preferences['saved_albums']),
                'top_genres': dict(sorted(
                    user_preferences['genre_preferences'].items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:10]),
                'listening_history_count': len(user_preferences['listening_history'])
            }
        })
    except Exception as e:
        logger.error(f"User preferences error: {e}")
        return jsonify({'error': 'Failed to get preferences'}), 500

@app.route('/api/my-collection')
def get_my_collection():
    """Get user's liked artists and saved albums"""
    try:
        # Convert liked_artists set to list with artist names
        liked_artists_data = []
        for artist_id in user_preferences['liked_artists']:
            # For now, we'll need to fetch artist details from Spotify
            # In a real app, we'd store this info when the user likes an artist
            try:
                if sp:
                    artist_info = sp.artist(artist_id)
                    liked_artists_data.append({
                        'artist_id': artist_id,
                        'artist_name': artist_info['name'],
                        'image': artist_info['images'][0]['url'] if artist_info['images'] else None,
                        'popularity': artist_info['popularity'],
                        'genres': artist_info['genres']
                    })
            except Exception as e:
                logger.warning(f"Could not fetch artist {artist_id}: {e}")
                # Fallback for artist we can't fetch
                liked_artists_data.append({
                    'artist_id': artist_id,
                    'artist_name': 'Unknown Artist',
                    'image': None,
                    'popularity': 0,
                    'genres': []
                })
        
        return jsonify({
            'success': True,
            'data': {
                'liked_artists': user_preferences['liked_artists_data'],
                'saved_albums': user_preferences['saved_albums'],
                'liked_count': len(user_preferences['liked_artists_data']),
                'saved_albums_count': len(user_preferences['saved_albums'])
            }
        })
    except Exception as e:
        logger.error(f"My collection error: {e}")
        return jsonify({'error': 'Failed to get collection'}), 500

@app.route('/api/health')
def health_check():
    """Health check endpoint"""
    try:
        # Test Spotify connection
        sp_status = 'connected' if sp else 'disconnected'
        
        return jsonify({
            'status': 'healthy',
            'spotify_api': sp_status,
            'timestamp': datetime.now().isoformat(),
            'version': '2.0.0'
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3847))
    debug = True  # Explicit debug mode
    print(f"Starting Flask app on port {port}")
    app.run(host='0.0.0.0', port=port, debug=debug)