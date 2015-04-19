import csv
import joblib
import lasagne
import nltk.tokenize
import numpy as np
import sys
import theano
import theano.tensor as T
from collections import OrderedDict
from scipy.spatial.distance import cosine
from sklearn.metrics import *
from theano.printing import Print as pp

from fuel.streams import DataStream
from fuel.schemes import ShuffledScheme
from TripleTextFile import TripleTextFile

sys.setrecursionlimit(10000)

TRAIN_FILE = 'data/trainset.csv_rand.rand.pkl'
VAL_FILE = 'data/valset.csv.rand.pkl'
TEST_FILE = 'data/testset.csv.rand.pkl'

TRAIN_DATA = joblib.load(TRAIN_FILE)
VAL_DATA = joblib.load(VAL_FILE)
TEST_DATA = joblib.load(TEST_FILE)

print "Done loading"

EN_DICT = joblib.load('embeddings/turian/vocab-50.pkl')
EMBEDDINGS = joblib.load('embeddings/turian/embeddings-50.pkl').astype(theano.config.floatX)

EMBEDDING_SIZE = EMBEDDINGS.shape[1]
HIDDEN_SIZE = EMBEDDING_SIZE
NUM_EPOCHS = 100
VOCAB_SIZE = len(EN_DICT)
MARGIN = 0.0
UNK_TOKEN = 'unknown'

def cosine_distance(x1, x2):
    return T.dot(x1, x2)# / T.sqrt(T.sum(x1 ** 2) * T.sum(x2 ** 2))

def relu(x):
    return T.switch(x<0, 0, x)

class RNN(object):
    def __init__(self, nh, ne, de, cs=1):
        # parameters of the model
        self.emb = theano.shared(EMBEDDINGS)
        self.Wx  = theano.shared(0.01 * np.random.uniform(-1.0, 1.0, (de * cs, nh)).astype(theano.config.floatX))
#        self.Wh  = theano.shared(1.00 * np.random.uniform(-1.0, 1.0, (nh, nh)).astype(theano.config.floatX))
        self.Wh  = theano.shared(np.eye(nh, dtype=theano.config.floatX))
        self.bh  = theano.shared(np.zeros(nh, dtype=theano.config.floatX))
        self.h0  = theano.shared(np.zeros(nh, dtype=theano.config.floatX))
#        self.M = theano.shared(np.random.randn(HIDDEN_SIZE, HIDDEN_SIZE).astype(theano.config.floatX))
        self.M = theano.shared(np.eye(HIDDEN_SIZE).astype(theano.config.floatX))

        # bundle
        self.params = [ self.emb, self.Wx, self.Wh, self.bh, self.h0, self.M ]
        self.names  = ['embeddings', 'Wx', 'Wh', 'bh', 'h0', 'M']
#        self.params = [ self.Wx, self.Wh, self.bh, self.h0 ]
#        self.names  = [ 'Wx', 'Wh', 'bh', 'h0']

        def recurrence(x_t, h_tm1):
            h_t = T.tanh(T.dot(x_t, self.Wx) + T.dot(h_tm1, self.Wh) + self.bh)
            return h_t

        x1_idxs = T.imatrix()
        x2_idxs = T.imatrix()

        x1 = self.emb[x1_idxs].reshape((x1_idxs.shape[1], de*cs))
        x2 = self.emb[x2_idxs].reshape((x2_idxs.shape[1], de*cs))

        h_x1, _ = theano.scan(fn=recurrence, sequences=x1, outputs_info=self.h0, n_steps=x1.shape[0])
        h_x2, _ = theano.scan(fn=recurrence, sequences=x2, outputs_info=self.h0, n_steps=x2.shape[0])

        e_x1 = h_x1[-1]
        e_x2 = h_x2[-1]
        y = T.iscalar()

        o = T.nnet.sigmoid(T.dot(T.dot(e_x1, self.M).reshape((-1,)), e_x2.reshape((-1,))))
        o = T.clip(o, 1e-7, 1.0-1e-7)

        cost = T.sum(T.nnet.binary_crossentropy(o, y))# + sum(T.sqrt(T.nlinalg.trace(T.dot(p.T, p))) for p in [self.emb, self.Wx, self.Wh, self.M])
        updates = lasagne.updates.adagrad(cost, self.params, learning_rate=0.01)
        self.train = theano.function(inputs=[x1_idxs, x2_idxs, y], outputs=[cost, e_x1, e_x2], updates=updates)
        self.predict = theano.function(inputs=[x1_idxs, x2_idxs], outputs=o)

def test_model(rnn, dataset):
    Y_pred = []
    Y_test = []
    for i,line in enumerate(dataset):
        X1, X2, Y = line[:3]
        if i % 1000 == 0:
            print "testing: %d" % i
        X1 = np.array(X1, dtype=np.int32)
        X2 = np.array(X2, dtype=np.int32)
        if X1.shape[1] == 0 or X2.shape[1] == 0:
            continue

        p = rnn.predict(X1.reshape((1,-1)), X2.reshape((1,-1)))
        Y_pred.append(0 if p < 0.5 else 1)
        Y = [1,0][Y]
        Y_test.append(Y)
    Y_test = np.array(Y_test)
    Y_pred = np.array(Y_pred)
    print classification_report(Y_test, Y_pred)

def main():
    rnn = RNN(nh=HIDDEN_SIZE, ne=VOCAB_SIZE, de=EMBEDDING_SIZE)
#    rnn = joblib.load('blobs/rnn.pkl')
    test_model(rnn, TRAIN_DATA)
    for e in xrange(NUM_EPOCHS):
        total_cost = 0
        for i,line in enumerate(TRAIN_DATA):
            X1, X2, Y = line[:3]
            X1 = np.array(X1, dtype=np.int32)
            X2 = np.array(X2, dtype=np.int32)
            if X1.shape[1] == 0 or X2.shape[1] == 0:
                continue
            Y = [1,0][Y]
            cost, e_x1, e_x2 = rnn.train(X1.reshape((1,-1)), X2.reshape((1,-1)), Y)
            total_cost += cost
        print "epoch: ", e, " avg cost: ", (total_cost / i)
        print "******************* TRAIN"
        test_model(rnn, TRAIN_DATA)
        print "******************* TEST"
        test_model(rnn, VAL_DATA)
        print "\n\n\n"
        joblib.dump(rnn, 'blobs/rnn.pkl')

if __name__ == '__main__':
    main()