const mongoose = require('mongoose');

const connectDB = async () => {
  await mongoose.connect(process.env.MONGO_URI, {
    dbName: 'taskhandler',
  });

  console.log('[db] MongoDB connected');
  console.log('[db] Database:', mongoose.connection.db.databaseName);
};

module.exports = connectDB;