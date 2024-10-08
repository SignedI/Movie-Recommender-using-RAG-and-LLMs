import pandas as pd
import requests
from google.colab import files
from transformers import LlamaForCausalLM, LlamaTokenizer
import pinecone
from openai.embeddings_utils import get_embedding

API_KEY = '' 

def get_imdb_data(movie_title):
    url = f"http://www.omdbapi.com/?t={movie_title}&apikey={API_KEY}"
    response = requests.get(url)
    data = response.json()
    if data['Response'] == 'True':
        return {
            'imdbRating': data.get('imdbRating', 'N/A'),
            'imdbVotes': data.get('imdbVotes', 'N/A')
        }
    else:
        return {'imdbRating': 'N/A', 'imdbVotes': 'N/A'}

def rate_movie(movie_title, user_rating):
    if movie_title in data['title'].values:
        prev_rating = data.loc[data['title'] == movie_title, 'new_user_rating'].values[0]
        prev_rating_count = data.loc[data['title'] == movie_title, 'rating_count'].values[0]

        new_rating_count = prev_rating_count + 1
        new_user_rating = ((prev_rating * prev_rating_count) + user_rating) / new_rating_count

        data.loc[data['title'] == movie_title, 'new_user_rating'] = new_user_rating
        data.loc[data['title'] == movie_title, 'rating_count'] = new_rating_count

        return new_rating_count
    else:
        print(f"Movie '{movie_title}' not found in the dataset.")
        return None

def update_embedding_after_30_ratings(movie_title):
    rating_count = data.loc[data['title'] == movie_title, 'rating_count'].values[0]
    
    if rating_count == 30:
        imdb_rating = float(data.loc[data['title'] == movie_title, 'imdbRating'].values[0])
        imdb_votes = int(data.loc[data['title'] == movie_title, 'imdbVotes'].values[0])
        a1 = imdb_rating * imdb_votes
        
        new_user_rating = data.loc[data['title'] == movie_title, 'new_user_rating'].values[0]
        a2 = new_user_rating
        
        new_imdb_rating = (a1 + 30 * a2) / (imdb_votes + 30)
        data.loc[data['title'] == movie_title, 'imdbRating'] = new_imdb_rating
        data.loc[data['title'] == movie_title, 'imdbVotes'] += 30
        data.loc[data['title'] == movie_title, 'rating_count'] = 0
        
        new_embedding = get_embedding(data.loc[data['title'] == movie_title, 'combined'].values[0], engine="text-embedding-ada-002")
        movie_id = data.loc[data['title'] == movie_title, 'title'].values[0] 
        index.upsert([(movie_id, new_embedding)])

        print(f"Updated IMDb rating and embedding for '{movie_title}' after 30 ratings.")
    else:
        print(f"Embedding not updated yet. {rating_count} ratings received for '{movie_title}'.")

pinecone.init(api_key="", environment="")
index_name = "movie-recommendations"
pinecone.create_index(index_name, dimension=len(data['embedding'][0]))

index = pinecone.Index(index_name)

model_name = "meta-llama/Llama-2-7b-chat-hf"
model = LlamaForCausalLM.from_pretrained(model_name)
tokenizer = LlamaTokenizer.from_pretrained(model_name)

def recommend_movie(user_query):
    query_embedding = get_embedding(user_query, engine="text-embedding-ada-002")
    search_results = index.query(query_embedding, top_k=5, include_values=True)
    
    context = ""
    for match in search_results['matches']:
        movie_info = data.loc[data['title'] == match['id'], 'combined'].values[0]
        context += f"{movie_info}\n"

    prompt = f"Given the user's preference: '{user_query}', and considering the following movies:\n{context}\nWhat movie would you recommend?"
    inputs = tokenizer(prompt, return_tensors="pt")
    output = model.generate(**inputs, max_new_tokens=100)
    recommendation = tokenizer.decode(output[0], skip_special_tokens=True)

    return recommendation

def user_input_query():
    user_query = input(f"What type of movies are you interested in? ")
    recommendation = recommend_movie(user_query)
    print("Recommendation:", recommendation)
    
    movie_title = input("Which movie did you pick: ")
    user_rating = float(input(f"Provide a rating for {movie_title}: "))
    rate_movie(movie_title, user_rating)
    update_embedding_after_30_ratings(movie_title)

netflix_df = pd.read_csv('netflix_titles.csv')

netflix_df['imdbRating'] = ''
netflix_df['imdbVotes'] = ''
netflix_df['new_user_rating'] = ''
netflix_df['rating_count'] = 0

for index, row in netflix_df.iterrows():
    title = row['title']
    imdb_data = get_imdb_data(title)
    netflix_df.at[index, 'imdbRating'] = imdb_data['imdbRating']
    netflix_df.at[index, 'imdbVotes'] = imdb_data['imdbVotes']

output_file = 'netflix_with_ratings.csv'
netflix_df.to_csv(output_file, index=False)
data = pd.read_csv("netflix_with_ratings.csv")

data['combined'] = data['type'] + " - " + data['title'] + " - " + \
                   data['director'] + " - " + data['cast'] + " - " + \
                   data['country'] + " - " + data['release_year'].astype(str) + \
                   " - " + data['listed_in'] + " - Rating: " + data['imdbRating'].astype(str)

data['embedding'] = data['combined'].apply(lambda x: get_embedding(x, engine="text-embedding-ada-002"))

movie_ids = data['title'].tolist()  
embeddings = data['embedding'].tolist()
vectors = list(zip(movie_ids, embeddings))

index.upsert(vectors)

user_input_query()


