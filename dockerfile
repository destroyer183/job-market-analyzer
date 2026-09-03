# get node
FROM node:20-slim AS frontend-build

# set working directory
WORKDIR /job market analyzer

# copy frontend
COPY /static/package.json ./

COPY /static/package-lock.json ./

# install npm
RUN npm-install

# compile typescript
RUN npx tsc











# get python
FROM python:3.11-slim

# get frontend
COPY --from=frontend-build /static ./

# get requirements
COPY requirements.txt ./

# install requirements
RUN pip install --no-cache-dir -r requirements.txt

# idk
COPY . .



# last thing to run everything
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]