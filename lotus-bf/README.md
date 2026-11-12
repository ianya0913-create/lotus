nvm install --lts # for install the latest long-term-support version of node.js
rm -rf node_modules package-lock.json # delete all incompatible packages
npm install # reinstall every packages according to pacakge.json
npm run dev # for local development
npm run build # for server deployment; upload the ./dist folder to a server